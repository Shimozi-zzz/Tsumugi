from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import re
from typing import Any
import zipfile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.models import AppStateSetting, Game, GameMediaPath, PlayRecord
from backend.scrapers.base import normalize_platform_badge
from backend.services import media_service
from backend.services.importers.base import (
    DuplicateStrategy,
    ExternalGameCandidate,
    ImportErrorItem,
    ImportSummary,
)

logger = logging.getLogger("tsumugi.services.importers.executor")

ZIP_URI_PREFIX = "zip://"
_WHITESPACE_RE = re.compile(r"\s+")
_VALID_STATUSES = {"todo", "playing", "done"}


def _normalize_title(text: str | None) -> str:
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", text.strip()).lower()


def _normalize_path(path_str: str | None) -> str:
    if not path_str:
        return ""
    return path_str.strip().replace("\\", "/").rstrip("/").lower()


def _normalize_vndb_id(raw: str | None) -> str:
    if not raw:
        return ""
    val = str(raw).strip().lower()
    if not val:
        return ""
    if val.isdigit():
        return f"v{val}"
    m = re.search(r"v(\d+)", val)
    return f"v{m.group(1)}" if m else val


def _normalize_digits_id(raw: str | None) -> str:
    if not raw:
        return ""
    m = re.search(r"(\d+)", str(raw).strip())
    return m.group(1) if m else ""


def _to_naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _pick_later_datetime(a: datetime | None, b: datetime | None) -> datetime | None:
    na = _to_naive_utc(a)
    nb = _to_naive_utc(b)
    if na is None:
        return nb
    if nb is None:
        return na
    return nb if nb > na else na


def _normalize_status(raw: str | None) -> str:
    val = (raw or "todo").strip().lower()
    if val in ("done", "completed", "finished", "beaten", "multiple"):
        return "done"
    if val in ("playing", "partial"):
        return "playing"
    if val in _VALID_STATUSES:
        return val
    return "todo"


def _build_external_ids(candidate: ExternalGameCandidate) -> dict[str, str]:
    ext_ids: dict[str, str] = {}
    if candidate.external_id:
        ext_ids[candidate.source_app] = candidate.external_id.strip()
    steam_id = _normalize_digits_id(candidate.steam_appid)
    if steam_id:
        ext_ids["steam"] = steam_id
    vndb_id = _normalize_vndb_id(candidate.vndb_id)
    if vndb_id:
        ext_ids["vndb"] = vndb_id
    bgm_id = _normalize_digits_id(candidate.bangumi_id)
    if bgm_id:
        ext_ids["bgm"] = bgm_id
    return ext_ids


def _dedupe_tags(tags: list[str], limit: int = 24) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        t = str(raw or "").strip()
        if not t or len(t) > 48:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(t)
        if len(result) >= limit:
            break
    return result


class _ExistingGameIndex:
    """用于高效去重匹配的现有游戏索引"""

    def __init__(self, games: list[Game]) -> None:
        self.by_id: dict[int, Game] = {}
        self.by_source_ext_id: dict[tuple[str, str], Game] = {}
        self.by_steam: dict[str, Game] = {}
        self.by_vndb: dict[str, Game] = {}
        self.by_bgm: dict[str, Game] = {}
        self.by_exe: dict[str, Game] = {}
        self.by_title: dict[str, Game] = {}
        for g in games:
            self.add(g)

    def add(self, game: Game) -> None:
        if game.id is not None:
            self.by_id[game.id] = game

        ext = game.external_ids if isinstance(game.external_ids, dict) else {}
        for source_key in ("playnite", "vnite"):
            val = str(ext.get(source_key) or "").strip()
            if val:
                self.by_source_ext_id.setdefault((source_key, val), game)

        steam = _normalize_digits_id(ext.get("steam"))
        if steam:
            self.by_steam.setdefault(steam, game)

        vndb = _normalize_vndb_id(ext.get("vndb"))
        if vndb:
            self.by_vndb.setdefault(vndb, game)

        bgm = _normalize_digits_id(game.bangumi_id or ext.get("bgm") or ext.get("bangumi"))
        if bgm:
            self.by_bgm.setdefault(bgm, game)

        if game.media and game.media.exe_path:
            exe_key = _normalize_path(game.media.exe_path)
            if exe_key:
                self.by_exe.setdefault(exe_key, game)

        for t in (game.title, game.sub_title):
            key = _normalize_title(t)
            if key:
                self.by_title.setdefault(key, game)

    def find_match(self, candidate: ExternalGameCandidate) -> Game | None:
        # 1. 同来源外部 ID 精确匹配
        ext_id = (candidate.external_id or "").strip()
        if ext_id:
            hit = self.by_source_ext_id.get((candidate.source_app, ext_id))
            if hit:
                return hit

        # 2. 跨平台权威外部 ID 匹配（Steam / VNDB / Bangumi）
        steam = _normalize_digits_id(candidate.steam_appid)
        if steam and steam in self.by_steam:
            return self.by_steam[steam]

        vndb = _normalize_vndb_id(candidate.vndb_id)
        if vndb and vndb in self.by_vndb:
            return self.by_vndb[vndb]

        bgm = _normalize_digits_id(candidate.bangumi_id)
        if bgm and bgm in self.by_bgm:
            return self.by_bgm[bgm]

        # 3. 本地可执行文件路径匹配
        exe_key = _normalize_path(candidate.executable_path)
        if exe_key and exe_key in self.by_exe:
            return self.by_exe[exe_key]

        # 4. 标题 / 原名归一化匹配
        for t in (candidate.name, candidate.original_name):
            key = _normalize_title(t)
            if key and key in self.by_title:
                return self.by_title[key]

        return None


def annotate_existing_games(
    candidates: list[ExternalGameCandidate],
    existing_games: list[Game],
) -> dict[str, Game]:
    """为扫描出的候选列表标注 exists_in_tsumugi 与 existing_game_id"""
    index = _ExistingGameIndex(existing_games)
    matched: dict[str, Game] = {}
    for cand in candidates:
        hit = index.find_match(cand)
        if hit is not None:
            cand.exists_in_tsumugi = True
            cand.existing_game_id = hit.id
            matched[cand.external_id] = hit
        else:
            cand.exists_in_tsumugi = False
            cand.existing_game_id = None
    return matched


def read_local_or_zip_image(source_ref: str) -> tuple[bytes, str] | None:
    """
    读取本地图片文件或 ZIP 备份包内图片成员字节：
    - 普通本地路径：直接读取文件字节
    - zip://<zip_path>::<member_name>：从 ZIP 包中只读提取图片字节
    """
    ref = (source_ref or "").strip()
    if not ref:
        return None

    if ref.startswith(ZIP_URI_PREFIX):
        rest = ref[len(ZIP_URI_PREFIX) :]
        if "::" not in rest:
            return None
        zip_path_str, member_name = rest.split("::", 1)
        zip_path = Path(zip_path_str)
        if not zip_path.is_file():
            return None
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                data = zf.read(member_name)
            if not data:
                return None
            return data, Path(member_name).name or "image.png"
        except Exception as exc:
            logger.warning("Failed to read zip image %s: %s", ref, exc)
            return None

    file_path = Path(ref)
    if not file_path.is_file():
        return None
    try:
        data = file_path.read_bytes()
        if not data:
            return None
        return data, file_path.name
    except OSError as exc:
        logger.warning("Failed to read local image %s: %s", ref, exc)
        return None


def copy_external_image_to_tsumugi(
    game_id: int,
    asset_type: str,
    source_ref: str,
) -> dict[str, str] | None:
    """
    独立拷贝外部本地封面/背景图至 Tsumugi 的 data/assets/{game_id}/ 目录：
    导入后完全脱离原软件独立运行（即使原软件或源目录被卸载/删除）。
    """
    loaded = read_local_or_zip_image(source_ref)
    if not loaded:
        return None

    content, filename = loaded
    try:
        return media_service.save_game_asset_bytes(
            game_id=game_id,
            asset_type=asset_type,
            filename=filename,
            content=content,
        )
    except Exception as exc:
        logger.warning(
            "Failed to convert/copy %s asset from %s for game %s: %s",
            asset_type,
            source_ref,
            game_id,
            exc,
        )
        return None


async def execute_external_import(
    db: AsyncSession,
    candidates: list[ExternalGameCandidate],
    duplicate_strategy: DuplicateStrategy = "skip",
) -> ImportSummary:
    """
    统一将选中的 ExternalGameCandidate 写入 Tsumugi 的 SQLite 数据库，
    执行去重合并策略并将本地视觉资产独立拷贝至 data/assets/{game_id}/。
    """
    summary = ImportSummary()
    if not candidates:
        return summary

    stmt = select(Game).options(selectinload(Game.media), selectinload(Game.play_record))
    existing_games = list((await db.execute(stmt)).scalars().all())
    index = _ExistingGameIndex(existing_games)

    for cand in candidates:
        try:
            existing = index.find_match(cand)
            if existing is not None:
                if duplicate_strategy == "skip":
                    summary.skipped += 1
                    continue

                # merge_playtime：保留现有资料，游玩时长取 max，更新更晚的 last_played_at，
                # 并在现有条目缺少封面/背景/外部 ID/启动路径时顺手补齐。
                if existing.play_record is None:
                    existing.play_record = PlayRecord(game_id=existing.id, total_seconds=0)

                ext_seconds = max(0, int(cand.playtime_seconds or 0))
                existing.play_record.total_seconds = max(
                    int(existing.play_record.total_seconds or 0),
                    ext_seconds,
                )
                existing.play_record.last_played_at = _pick_later_datetime(
                    existing.play_record.last_played_at,
                    cand.last_played_at,
                )

                # 顺手补齐外部 ID（重新赋新字典以触发 SQLAlchemy JSON 变更追踪）
                merged_ext_ids: dict[str, Any] = dict(existing.external_ids or {})
                cand_ext_ids = _build_external_ids(cand)
                ext_changed = False
                for k, v in cand_ext_ids.items():
                    if v and not str(merged_ext_ids.get(k) or "").strip():
                        merged_ext_ids[k] = v
                        ext_changed = True
                if ext_changed:
                    existing.external_ids = merged_ext_ids

                bgm_id = _normalize_digits_id(cand.bangumi_id)
                if bgm_id and not (existing.bangumi_id or "").strip():
                    existing.bangumi_id = bgm_id

                if existing.media is None:
                    existing.media = GameMediaPath(game_id=existing.id)

                if not (existing.media.exe_path or "").strip() and (cand.executable_path or "").strip():
                    existing.media.exe_path = cand.executable_path.strip()

                if not (existing.media.cover_path or "").strip() and cand.cover_path:
                    copied_cover = copy_external_image_to_tsumugi(existing.id, "cover", cand.cover_path)
                    if copied_cover:
                        existing.media.cover_path = copied_cover["path"]
                        if copied_cover.get("thumb_path"):
                            existing.media.cover_thumb_path = copied_cover["thumb_path"]

                if not (existing.media.hero_bg_path or "").strip() and cand.background_path:
                    copied_bg = copy_external_image_to_tsumugi(existing.id, "hero", cand.background_path)
                    if copied_bg:
                        existing.media.hero_bg_path = copied_bg["path"]

                index.add(existing)
                summary.merged += 1
                summary.merged_ids.append(existing.id)
                continue

            # 新增入库
            title = (cand.name or "").strip()
            if not title:
                raise ValueError("候选条目缺少游戏标题")

            ext_ids = _build_external_ids(cand)
            bgm_id = _normalize_digits_id(cand.bangumi_id)
            platform_badge = normalize_platform_badge(
                cand.platform_source or ("Steam" if ext_ids.get("steam") else "PC"),
                ext_ids,
            ) or "PC"

            game = Game(
                title=title[:255],
                sub_title=(cand.original_name or "").strip()[:255],
                pinyin_initials=media_service.generate_pinyin_initials(title)[:128],
                developer=", ".join(d.strip() for d in cand.developers if d and d.strip())[:128],
                publisher=", ".join(p.strip() for p in cand.publishers if p and p.strip())[:128],
                release_date=(cand.release_date or "").strip()[:32],
                synopsis=(cand.description or "").strip(),
                tags=_dedupe_tags(cand.tags),
                external_ids=ext_ids,
                locked_fields=[],
                bangumi_id=bgm_id[:64],
                series="",
                status=_normalize_status(cand.play_status),
                edition="collector",
                is_nsfw=False,
                source_platform=platform_badge[:32],
            )
            game.media = GameMediaPath(
                exe_path=(cand.executable_path or "").strip()[:512],
                launch_mode="direct",
            )
            game.play_record = PlayRecord(
                total_seconds=max(0, int(cand.playtime_seconds or 0)),
                last_played_at=_to_naive_utc(cand.last_played_at),
            )

            db.add(game)
            await db.flush()

            # 独立拷贝本地封面与背景图至 data/assets/{game.id}/
            if cand.cover_path:
                copied_cover = copy_external_image_to_tsumugi(game.id, "cover", cand.cover_path)
                if copied_cover:
                    game.media.cover_path = copied_cover["path"]
                    if copied_cover.get("thumb_path"):
                        game.media.cover_thumb_path = copied_cover["thumb_path"]

            if cand.background_path:
                copied_bg = copy_external_image_to_tsumugi(game.id, "hero", cand.background_path)
                if copied_bg:
                    game.media.hero_bg_path = copied_bg["path"]

            index.add(game)
            summary.imported += 1
            summary.imported_ids.append(game.id)
        except Exception as exc:
            logger.warning("External import failed for %s (%s): %s", cand.name, cand.external_id, exc)
            summary.errors.append(
                ImportErrorItem(
                    external_id=cand.external_id,
                    name=cand.name,
                    error=str(exc),
                )
            )

    if summary.imported_ids:
        setting = await db.get(AppStateSetting, "last_active_game_id")
        if setting:
            setting.value = summary.imported_ids[-1]
        else:
            db.add(AppStateSetting(key="last_active_game_id", value=summary.imported_ids[-1]))

    await db.commit()
    return summary
