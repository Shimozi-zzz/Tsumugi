from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any
import zipfile

from backend.services.importers.base import (
    BaseLibraryImporter,
    DetectResult,
    ExternalGameCandidate,
    ImporterError,
)
from backend.services.importers.executor import ZIP_URI_PREFIX
from backend.services.importers.leveldb_reader import (
    PouchDBParseResult,
    discover_leveldb_directories,
    parse_pouchdb_directory,
    sniff_image_extension,
)
from backend.services.importers.playnite import clean_html_description

logger = logging.getLogger("tsumugi.services.importers.vnite")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
LEVELDB_MARKERS = {"current", "lock"}
IMAGE_DIR_NAMES = {"images", "attachments", "covers", "backgrounds", "media", "assets"}
LOCAL_META_FILENAMES = {"game-local.json", "games-local.json", "games_local.json", "local.json"}
PRIMARY_GAME_FILENAMES = ("games.json", "game.json", "database.json", "data.json", "backup.json")

_LOCAL_SUBDB_NAMES = {"game-local", "games-local", "game_local", "games_local", "local"}
_ATTACHMENT_SUBDB_NAMES = {"attachments", "attachment", "game-attachments", "game_attachments", "images", "image"}
_IGNORED_GAME_SUBDB_NAMES = {
    "config",
    "config-local",
    "config_local",
    "plugin",
    "plugins",
    "account",
    "accounts",
    "sync",
    "collection",
    "collections",
    "game-collection",
    "game-collections",
    "memory",
    "memories",
    "tag",
    "tags",
    "scraper",
    "timer",
    "timers",
}

_STEAM_URL_RE = re.compile(r"store\.steampowered\.com/app/(\d+)", re.IGNORECASE)
_VNDB_URL_RE = re.compile(r"vndb\.org/(v\d+)", re.IGNORECASE)
_BGM_URL_RE = re.compile(r"(?:bgm\.tv|bangumi\.tv|chii\.in)/subject/(\d+)", re.IGNORECASE)
_YMGAL_URL_RE = re.compile(r"ymgal\.games/(ga\d+)", re.IGNORECASE)
_SPLIT_STR_RE = re.compile(r"[,，/、;；]+")
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _to_str_list(val: Any) -> list[str]:
    if val is None:
        return []
    if isinstance(val, str):
        return [s.strip() for s in _SPLIT_STR_RE.split(val) if s.strip()]
    if isinstance(val, (list, tuple)):
        out: list[str] = []
        for item in val:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("label") or item.get("title") or "").strip()
                if name:
                    out.append(name)
            else:
                s = str(item or "").strip()
                if s:
                    out.append(s)
        return out
    return []


def _parse_iso_datetime(val: Any) -> datetime | None:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, (int, float)):
        num = float(val)
        if num <= 0:
            return None
        ts = num / 1000.0 if abs(num) > 1e11 else num
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(val, str):
        raw = val.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(raw[:19], fmt)
                except ValueError:
                    continue
    return None


def _normalize_release_date(val: Any) -> str:
    if val is None or val == "":
        return ""
    s = str(val).strip()
    if len(s) >= 10 and re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    if re.match(r"^\d{4}/\d{1,2}/\d{1,2}", s):
        parts = s[:10].split("/")
        return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    return s[:32]


def _normalize_vndb(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if not s:
        return ""
    if s.isdigit():
        return f"v{s}"
    m = re.search(r"v(\d+)", s)
    return f"v{m.group(1)}" if m else ""


def _normalize_digits(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    m = re.search(r"(\d+)", s)
    return m.group(1) if m else ""


def _normalize_ymgal(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    m = re.search(r"ga(\d+)", s, re.IGNORECASE)
    if m:
        return f"GA{m.group(1)}"
    if s.isdigit():
        return f"GA{s}"
    return ""


def _extract_ids_from_sites(sites: Any) -> tuple[str, str, str, str]:
    steam_id, vndb_id, bgm_id, ymgal_id = "", "", "", ""
    if not isinstance(sites, list):
        return steam_id, vndb_id, bgm_id, ymgal_id
    for entry in sites:
        url = ""
        if isinstance(entry, dict):
            url = str(entry.get("url") or entry.get("Url") or entry.get("href") or "").strip()
        elif isinstance(entry, str):
            url = entry.strip()
        if not url:
            continue
        if not steam_id:
            m = _STEAM_URL_RE.search(url)
            if m:
                steam_id = m.group(1)
        if not vndb_id:
            m = _VNDB_URL_RE.search(url)
            if m:
                vndb_id = m.group(1).lower()
        if not bgm_id:
            m = _BGM_URL_RE.search(url)
            if m:
                bgm_id = m.group(1)
        if not ymgal_id:
            m = _YMGAL_URL_RE.search(url)
            if m:
                ymgal_id = m.group(1).upper()
    return steam_id, vndb_id, bgm_id, ymgal_id


def _sum_timers_seconds(timers: Any) -> int:
    if not isinstance(timers, list):
        return 0
    total = 0.0
    for item in timers:
        if not isinstance(item, dict):
            continue
        start = _parse_iso_datetime(item.get("start"))
        end = _parse_iso_datetime(item.get("end"))
        if start and end and end > start:
            total += (end - start).total_seconds()
    return max(0, int(round(total)))


def normalize_vnite_playtime_seconds(
    doc: dict[str, Any],
    record: dict[str, Any],
) -> int:
    """
    兼容 Vnite 不同版本的游玩时长单位（自动判断毫秒 vs 秒，统一转为秒）：
    1. 优先识别显式单位字段（playTimeMs / playTimeSeconds）；
    2. 若存在 timers 明细数组，借助明细总秒数直接判定单位；
    3. 遵循 Vnite v2/v3 规范（record 内通常为毫秒）与合理量级启发式阈值。
    """
    # 1. 显式字段名
    for container in (record, doc):
        for key in ("playTimeMs", "playtime_ms", "playingTimeMs"):
            val = container.get(key)
            if val is not None and val != "":
                try:
                    return max(0, int(round(float(val) / 1000.0)))
                except (TypeError, ValueError):
                    pass
        for key in ("playTimeSeconds", "playtime_seconds", "playtimeSeconds"):
            val = container.get(key)
            if val is not None and val != "":
                try:
                    return max(0, int(round(float(val))))
                except (TypeError, ValueError):
                    pass

    raw_val: Any = None
    from_record = False
    for key in ("playTime", "playtime", "playingTime", "totalPlayTime"):
        if key in record and record[key] is not None and record[key] != "":
            raw_val = record[key]
            from_record = True
            break
    if raw_val is None:
        for key in ("playTime", "playtime", "playingTime", "totalPlayTime"):
            if key in doc and doc[key] is not None and doc[key] != "":
                raw_val = doc[key]
                break

    timers = record.get("timers") if isinstance(record.get("timers"), list) else doc.get("timers")
    timer_seconds = _sum_timers_seconds(timers)

    if raw_val is None:
        return timer_seconds

    try:
        num = float(raw_val)
    except (TypeError, ValueError):
        return timer_seconds

    if num <= 0:
        return timer_seconds

    # 2. 若有 timers 真实区间，直接比对秒 vs 毫秒误差
    if timer_seconds > 0:
        diff_as_sec = abs(num - timer_seconds)
        diff_as_ms = abs(num - timer_seconds * 1000.0)
        if diff_as_ms < diff_as_sec:
            return max(0, int(round(num / 1000.0)))
        return max(0, int(round(num)))

    # 3. 检查显式单位提示
    unit_hint = str(record.get("playTimeUnit") or doc.get("playTimeUnit") or "").strip().lower()
    if unit_hint in ("ms", "millisecond", "milliseconds"):
        return max(0, int(round(num / 1000.0)))
    if unit_hint in ("s", "sec", "second", "seconds"):
        return max(0, int(round(num)))

    # 4. Vnite v2/v3 record 含 timers/dailyPlayTimes 字段时默认使用毫秒；大数值（>= 500,000）亦按毫秒归一化
    has_v2_record_shape = from_record and (
        "timers" in record or "dailyPlayTimes" in record or "lastRunDate" in record
    )
    if num >= 500_000:
        return max(0, int(round(num / 1000.0)))
    if has_v2_record_shape and num >= 60_000 and int(num) % 1000 == 0:
        return max(0, int(round(num / 1000.0)))

    return max(0, int(round(num)))


def _map_vnite_status(raw_status: Any, playtime_seconds: int) -> str:
    val = str(raw_status or "").strip().lower()
    if val in ("finished", "multiple", "completed", "done", "已通关", "已完成", "通关"):
        return "done"
    if val in ("playing", "partial", "游玩中", "攻略中", "在玩"):
        return "playing"
    if val in ("unplayed", "shelved", "todo", "未开始", "搁置", "想玩"):
        return "todo"
    return "playing" if playtime_seconds > 0 else "todo"


def _looks_like_game_doc(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    if obj.get("_deleted") is True:
        return False
    meta = obj.get("metadata")
    if isinstance(meta, dict) and any(
        k in meta for k in ("name", "originalName", "developers", "vndbId", "steamId", "bangumiId", "ymgalId")
    ):
        return True
    return any(
        k in obj
        for k in (
            "name",
            "title",
            "originalName",
            "gamePath",
            "playTime",
            "vndbId",
            "bangumiId",
            "ymgalId",
        )
    )


def _looks_like_local_doc(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    if isinstance(obj.get("path"), dict) or isinstance(obj.get("launcher"), dict):
        return True
    return any(k in obj for k in ("gamePath", "game_path", "exePath", "exe_path", "executablePath"))


def _is_non_empty_value(val: Any) -> bool:
    if val is None:
        return False
    if isinstance(val, (str, list, dict)):
        return len(val) > 0
    return True


def _deep_merge_docs(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """合并同一 _id 跨子库文档：递归合并嵌套 dict，避免空值覆盖已有有效字段"""
    merged = dict(base)
    for k, v in overlay.items():
        if k not in merged or not _is_non_empty_value(merged[k]):
            merged[k] = v
        elif isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _deep_merge_docs(merged[k], v)
        elif _is_non_empty_value(v) and k in ("path", "launcher", "_attachments"):
            merged[k] = v
    return merged


def _prepare_attachment_staging_dir(source_key: str) -> Path:
    """为单次 LevelDB 扫描创建隔离且可复用的临时附件目录（绝不写入 Vnite 源目录）"""
    digest = hashlib.sha1(source_key.encode("utf-8", errors="ignore")).hexdigest()[:16]
    stage_dir = Path(tempfile.gettempdir()) / "tsumugi_vnite_attachments" / digest
    if stage_dir.exists():
        shutil.rmtree(stage_dir, ignore_errors=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    return stage_dir


def _write_staged_attachment(
    stage_dir: Path,
    game_id: str,
    role: str,
    raw_bytes: bytes,
    *,
    content_type: str = "",
    filename: str = "",
) -> str:
    safe_gid = _SAFE_FILENAME_RE.sub("_", game_id).strip("._")[:48] or "game"
    ext = sniff_image_extension(raw_bytes, content_type=content_type, filename=filename)
    key_hash = hashlib.sha1(f"{game_id}:{role}".encode("utf-8")).hexdigest()[:8]
    out_file = stage_dir / f"{safe_gid}_{key_hash}_{role}{ext}"
    out_file.write_bytes(raw_bytes)
    return str(out_file.resolve())


def _resolve_attachment_role(att_name: str, doc_id: str = "") -> str:
    """识别附件角色（cover / background / icon / other）"""
    low_name = att_name.replace("\\", "/").lower()
    low_id = doc_id.replace("\\", "/").lower()
    stem = Path(low_name).stem
    if any(k in stem for k in ("background", "backdrop", "hero", "wallpaper", "banner", "bg")):
        return "background"
    if any(k in stem for k in ("cover", "poster", "boxart", "front")):
        return "cover"
    if any(k in stem for k in ("icon", "favicon", "logo")):
        return "icon"
    role_from_id = _classify_image_role(low_id)
    if role_from_id in ("cover", "background"):
        return role_from_id
    return "other"


def _extract_attachment_bytes_from_meta(
    att_meta: dict[str, Any],
    attachments_by_digest: dict[str, bytes],
) -> bytes | None:
    # 1. 优先通过 digest 在 attach-binary-store 中查找
    digest = str(att_meta.get("digest") or "").strip()
    if digest:
        if digest in attachments_by_digest:
            return attachments_by_digest[digest]
        if digest.startswith("md5-") and digest[4:] in attachments_by_digest:
            return attachments_by_digest[digest[4:]]
        if not digest.startswith("md5-") and f"md5-{digest}" in attachments_by_digest:
            return attachments_by_digest[f"md5-{digest}"]

    # 2. 兜底支持内联 base64 data 字段
    inline_data = att_meta.get("data")
    if isinstance(inline_data, str) and inline_data.strip():
        cleaned = inline_data.strip()
        if cleaned.startswith("data:") and "," in cleaned:
            cleaned = cleaned.split(",", 1)[1].strip()
        try:
            decoded = base64.b64decode(cleaned, validate=False)
            if decoded:
                return decoded
        except Exception:
            pass
    return None


def _extract_game_id_from_attachment_doc_id(doc_id: str, known_game_ids: set[str]) -> str | None:
    """从独立附件子库的 doc_id 中反推游戏 ID（如 <gameId>、games/<gameId>/cover.webp 等）"""
    low = doc_id.strip().lower()
    if low in known_game_ids:
        return low
    parts = [p.strip().lower() for p in re.split(r"[/\\:]+", doc_id) if p.strip()]
    for part in parts:
        if part in known_game_ids:
            return part
        stem = Path(part).stem.lower()
        if stem in known_game_ids:
            return stem
    return None


def _safe_extract_zip(zf: zipfile.ZipFile, dest_dir: Path) -> None:
    """安全解压 ZIP 至临时目录（防止 Zip Slip 路径穿越）"""
    dest_root = dest_dir.resolve()
    for info in zf.infolist():
        if info.is_dir():
            continue
        rel_parts = [p for p in Path(info.filename.replace("\\", "/")).parts if p not in ("", ".", "..", "/")]
        if not rel_parts:
            continue
        target = (dest_root / Path(*rel_parts)).resolve()
        if not target.is_relative_to(dest_root):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info, "r") as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)


def _extract_games_and_locals_from_json(
    data: Any,
) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, dict[str, Any]]]:
    """
    兼容多种 Vnite JSON 导出结构，提取 (game_id, game_doc) 列表及可选 game_local 映射。
    """
    games: list[tuple[str, dict[str, Any]]] = []
    locals_map: dict[str, dict[str, Any]] = {}

    if isinstance(data, list):
        for idx, item in enumerate(data):
            if _looks_like_game_doc(item):
                gid = str(item.get("_id") or item.get("id") or f"vnite_{idx + 1}").strip()
                games.append((gid, item))
        return games, locals_map

    if not isinstance(data, dict):
        return games, locals_map

    # 先提取可能附带的 local 路径表
    for lkey in ("gameLocal", "gamesLocal", "game_local", "games_local", "local", "locals"):
        lval = data.get(lkey)
        if isinstance(lval, dict):
            for k, v in lval.items():
                if isinstance(v, dict):
                    lid = str(v.get("_id") or v.get("id") or k).strip()
                    locals_map[lid] = v
        elif isinstance(lval, list):
            for v in lval:
                if isinstance(v, dict):
                    lid = str(v.get("_id") or v.get("id") or "").strip()
                    if lid:
                        locals_map[lid] = v

    # 容器键：games / game / docs / rows / items / data
    for gkey in ("games", "game", "items", "docs", "data"):
        container = data.get(gkey)
        if isinstance(container, list):
            for idx, item in enumerate(container):
                if _looks_like_game_doc(item):
                    gid = str(item.get("_id") or item.get("id") or f"vnite_{idx + 1}").strip()
                    games.append((gid, item))
            if games:
                return games, locals_map
        elif isinstance(container, dict):
            for k, v in container.items():
                if _looks_like_game_doc(v):
                    gid = str(v.get("_id") or v.get("id") or k).strip()
                    games.append((gid, v))
            if games:
                return games, locals_map

    # PouchDB / CouchDB rows 导出结构：{"rows": [{"id": ..., "doc": {...}}]}
    rows = data.get("rows")
    if isinstance(rows, list):
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            doc = row.get("doc") if isinstance(row.get("doc"), dict) else row
            if _looks_like_game_doc(doc):
                gid = str(doc.get("_id") or row.get("id") or f"vnite_{idx + 1}").strip()
                games.append((gid, doc))
        if games:
            return games, locals_map

    # 单游戏文档 JSON
    if _looks_like_game_doc(data) and not any(
        isinstance(v, dict) and _looks_like_game_doc(v) for v in data.values()
    ):
        gid = str(data.get("_id") or data.get("id") or "vnite_1").strip()
        return [(gid, data)], locals_map

    # Vnite 标准 gameDocs 字典结构：{ "<game_id>": { "_id": "...", "metadata": {...}, "record": {...} } }
    for k, v in data.items():
        if isinstance(v, dict) and _looks_like_game_doc(v):
            gid = str(v.get("_id") or v.get("id") or k).strip()
            games.append((gid, v))

    return games, locals_map


def _parse_local_doc_map(data: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict):
                lid = str(v.get("_id") or v.get("id") or k).strip()
                if lid:
                    out[lid] = v
    elif isinstance(data, list):
        for v in data:
            if isinstance(v, dict):
                lid = str(v.get("_id") or v.get("id") or "").strip()
                if lid:
                    out[lid] = v
    return out


def _classify_image_role(rel_path: str) -> str:
    """根据文件名或父路径判断图片属于 cover 还是 background"""
    low = rel_path.replace("\\", "/").lower()
    stem = Path(low).stem
    if any(k in stem for k in ("background", "backdrop", "hero", "wallpaper", "banner", "bg")):
        return "background"
    if any(k in stem for k in ("cover", "poster", "boxart", "front")):
        return "cover"
    if "/backgrounds/" in low or low.startswith("backgrounds/"):
        return "background"
    if "/covers/" in low or low.startswith("covers/"):
        return "cover"
    return "other"


def _index_directory_images(root_dir: Path) -> dict[str, dict[str, str]]:
    """
    递归扫描本地图片目录（images/、attachments/、covers/、backgrounds/、media/），
    构建 {game_id_lower: {"cover": abs_path, "background": abs_path}} 索引。
    """
    index: dict[str, dict[str, str]] = {}
    if not root_dir.is_dir():
        return index

    search_roots: list[Path] = []
    for sub_name in IMAGE_DIR_NAMES:
        cand = root_dir / sub_name
        if cand.is_dir():
            search_roots.append(cand)
    # 兼容 Vnite 常见嵌套目录结构（如 app/attachments 或 上级目录 images/）
    for extra in (
        root_dir / "app" / "attachments",
        root_dir / "app" / "images",
        root_dir.parent / "attachments",
        root_dir.parent / "images",
    ):
        if extra.is_dir() and extra not in search_roots:
            search_roots.append(extra)

    if not search_roots:
        search_roots = [root_dir]

    visited_dirs: set[Path] = set()
    for base in search_roots:
        resolved_base = base.resolve()
        if resolved_base in visited_dirs:
            continue
        visited_dirs.add(resolved_base)
        for img_file in resolved_base.rglob("*"):
            if not img_file.is_file() or img_file.suffix.lower() not in IMAGE_EXTS:
                continue
            rel = img_file.relative_to(resolved_base).as_posix()
            parts = [p for p in rel.split("/") if p]
            role = _classify_image_role(rel)
            stem = img_file.stem

            # 提取候选游戏 ID：优先使用所在目录名（如 images/<gameId>/cover.png），再兼容文件名（covers/<gameId>.jpg 或 <gameId>_cover.png）
            candidate_ids: list[str] = []
            for p in reversed(parts[:-1]):
                pl = p.lower()
                if pl not in IMAGE_DIR_NAMES and pl not in {"game", "games"}:
                    candidate_ids.append(pl)
                    break
            stem_clean = re.sub(r"[_\-.]?(cover|background|backdrop|hero|bg)$", "", stem, flags=re.IGNORECASE)
            if stem_clean and stem_clean.lower() not in {"cover", "background", "backdrop", "hero", "bg", "icon", "logo"}:
                candidate_ids.append(stem_clean.lower())

            for cid in candidate_ids:
                bucket = index.setdefault(cid, {})
                if role == "cover" and "cover" not in bucket:
                    bucket["cover"] = str(img_file.resolve())
                elif role == "background" and "background" not in bucket:
                    bucket["background"] = str(img_file.resolve())
                elif role == "other" and "cover" not in bucket:
                    bucket["cover"] = str(img_file.resolve())

    return index


def _index_zip_images(zip_path: Path, member_names: list[str]) -> dict[str, dict[str, str]]:
    """为 ZIP 备份包内的图片建立索引，路径编码为 zip://<abs_zip>::<member>"""
    index: dict[str, dict[str, str]] = {}
    abs_zip = str(zip_path.resolve())
    for member in member_names:
        if member.endswith("/"):
            continue
        p = Path(member)
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        parts = [seg for seg in member.replace("\\", "/").split("/") if seg]
        role = _classify_image_role(member)
        stem = p.stem

        candidate_ids: list[str] = []
        for seg in reversed(parts[:-1]):
            sl = seg.lower()
            if sl not in IMAGE_DIR_NAMES and sl not in {"game", "games", "app", "database"}:
                candidate_ids.append(sl)
                break
        stem_clean = re.sub(r"[_\-.]?(cover|background|backdrop|hero|bg)$", "", stem, flags=re.IGNORECASE)
        if stem_clean and stem_clean.lower() not in {"cover", "background", "backdrop", "hero", "bg", "icon", "logo"}:
            candidate_ids.append(stem_clean.lower())

        uri = f"{ZIP_URI_PREFIX}{abs_zip}::{member}"
        for cid in candidate_ids:
            bucket = index.setdefault(cid, {})
            if role == "cover" and "cover" not in bucket:
                bucket["cover"] = uri
            elif role == "background" and "background" not in bucket:
                bucket["background"] = uri
            elif role == "other" and "cover" not in bucket:
                bucket["cover"] = uri
    return index


def _has_leveldb_files(directory: Path) -> bool:
    """探测目录或其子目录中是否存在 LevelDB 二进制存储文件"""
    if not directory.is_dir():
        return False
    checked = 0
    for item in directory.rglob("*"):
        checked += 1
        if checked > 600:
            break
        if not item.is_file():
            continue
        lname = item.name.lower()
        if (
            lname in LEVELDB_MARKERS
            or lname.startswith("manifest-")
            or item.suffix.lower() in {".ldb", ".sst"}
        ):
            return True
    return False


def _has_readable_json_in_dir(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    for name in PRIMARY_GAME_FILENAMES:
        if (directory / name).is_file():
            return True
    for sub in ("games", "game"):
        sub_dir = directory / sub
        if sub_dir.is_dir() and any(sub_dir.glob("*.json")):
            return True
    return False


class VniteImporter(BaseLibraryImporter):
    """Vnite Galgame 库导入适配器（支持 JSON/ZIP 备份文件与本地目录扫描）"""

    source_name = "vnite"

    def detect_path(self) -> DetectResult:
        candidates: list[Path] = []
        appdata = os.environ.get("APPDATA", "").strip()
        roots: list[Path] = []

        if appdata:
            roots.extend([Path(appdata) / "vnite", Path(appdata) / "Vnite"])
        home_roaming = Path.home() / "AppData" / "Roaming"
        for name in ("vnite", "Vnite"):
            p = home_roaming / name
            if p not in roots:
                roots.append(p)

        for root in roots:
            candidates.extend(
                [
                    root / "app" / "database",
                    root / "database",
                    root,
                ]
            )

        unique_strs: list[str] = []
        seen: set[str] = set()
        for c in candidates:
            s = str(c)
            if s not in seen:
                seen.add(s)
                unique_strs.append(s)

        # 1. 优先返回含可直接读取 JSON 的目录
        for c in candidates:
            if _has_readable_json_in_dir(c):
                return DetectResult(
                    source="vnite",
                    detected_path=str(c.resolve()),
                    valid=True,
                    message="已自动探测到 Vnite JSON 数据目录",
                    candidates=unique_strs,
                )

        # 2. 探测到 Vnite 本地 LevelDB / PouchDB 目录，支持直接只读解析
        for c in candidates:
            if c.is_dir():
                if _has_leveldb_files(c):
                    return DetectResult(
                        source="vnite",
                        detected_path=str(c.resolve()),
                        valid=True,
                        message="已探测到 Vnite 本地数据库目录，可直接点击「扫描游戏库」只读解析（也兼容导入 .json / .zip 备份）",
                        candidates=unique_strs,
                    )
                return DetectResult(
                    source="vnite",
                    detected_path=str(c.resolve()),
                    valid=True,
                    message="已自动探测到 Vnite 本地目录，可直接扫描或填写导出的 .json / .zip 备份路径",
                    candidates=unique_strs,
                )

        return DetectResult(
            source="vnite",
            detected_path=unique_strs[0] if unique_strs else "",
            valid=False,
            message="未在默认目录探测到 Vnite，可手动填写 Vnite 数据目录或导出的 .json / .zip 备份文件路径",
            candidates=unique_strs,
        )

    def scan(self, path: str) -> list[ExternalGameCandidate]:
        raw = (path or "").strip()
        if not raw:
            raise ImporterError("请先填写 Vnite 数据目录或导出的 .json / .zip 备份文件路径")

        target = Path(raw).expanduser()
        if not target.exists():
            raise ImporterError(f"指定的 Vnite 路径不存在: {raw}")

        if target.is_file():
            suffix = target.suffix.lower()
            if suffix == ".json":
                return self._scan_json_file(target)
            if suffix == ".zip":
                return self._scan_zip_file(target)
            raise ImporterError(
                f"不支持的 Vnite 文件格式 ({suffix or '无后缀'})，请选择 .json / .zip 备份文件或数据目录"
            )

        return self._scan_directory(target)

    def _scan_json_file(self, json_file: Path) -> list[ExternalGameCandidate]:
        try:
            data = json.loads(json_file.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            raise ImporterError(f"解析 Vnite JSON 文件失败: {exc}") from exc

        game_pairs, locals_map = _extract_games_and_locals_from_json(data)
        if not game_pairs:
            raise ImporterError(f"在 {json_file.name} 中未识别到有效的 Vnite 游戏数据")

        # 顺便检查同目录下是否存在 game-local.json 补充本地启动路径
        for local_name in LOCAL_META_FILENAMES:
            sibling = json_file.parent / local_name
            if sibling.is_file() and sibling != json_file:
                try:
                    locals_map.update(
                        _parse_local_doc_map(json.loads(sibling.read_text(encoding="utf-8-sig")))
                    )
                except Exception:
                    pass

        img_index = _index_directory_images(json_file.parent)
        return self._build_candidates(game_pairs, locals_map, img_index, base_dir=json_file.parent)

    def _scan_zip_file(self, zip_file: Path) -> list[ExternalGameCandidate]:
        try:
            zf = zipfile.ZipFile(zip_file, "r")
        except Exception as exc:
            raise ImporterError(f"无法打开 Vnite ZIP 备份文件: {exc}") from exc

        with zf:
            names = zf.namelist()
            img_index = _index_zip_images(zip_file, names)

            game_pairs: list[tuple[str, dict[str, Any]]] = []
            locals_map: dict[str, dict[str, Any]] = {}
            has_leveldb_in_zip = False

            json_members: list[str] = []
            for member in names:
                if member.endswith("/"):
                    continue
                lname = Path(member).name.lower()
                if lname in LEVELDB_MARKERS or lname.startswith("manifest-") or lname.endswith((".ldb", ".sst", ".log")):
                    has_leveldb_in_zip = True
                if lname.endswith(".json"):
                    json_members.append(member)

            # 优先读取 local 路径文件
            for member in json_members:
                lname = Path(member).name.lower()
                lower_member = member.replace("\\", "/").lower()
                if lname in LOCAL_META_FILENAMES or "/game-local/" in lower_member or lower_member.startswith("game-local/"):
                    try:
                        parsed = json.loads(zf.read(member).decode("utf-8-sig"))
                        locals_map.update(_parse_local_doc_map(parsed))
                    except Exception:
                        pass

            # 再按优先级读取主 games JSON 或逐游戏 JSON
            def _priority(m: str) -> tuple[int, str]:
                lname = Path(m).name.lower()
                if lname in PRIMARY_GAME_FILENAMES:
                    return (PRIMARY_GAME_FILENAMES.index(lname), m)
                return (len(PRIMARY_GAME_FILENAMES), m)

            for member in sorted(json_members, key=_priority):
                lname = Path(member).name.lower()
                lower_member = member.replace("\\", "/").lower()
                if lname in LOCAL_META_FILENAMES or "/game-local/" in lower_member or lower_member.startswith("game-local/"):
                    continue
                if lname in {"config.json", "settings.json", "package.json", "collections.json"}:
                    continue
                try:
                    parsed = json.loads(zf.read(member).decode("utf-8-sig"))
                except Exception:
                    continue
                extracted_games, extracted_locals = _extract_games_and_locals_from_json(parsed)
                if extracted_locals:
                    locals_map.update(extracted_locals)
                if extracted_games:
                    game_pairs.extend(extracted_games)
                    # 若已从主数据文件解析出列表，避免重复扫描其他辅助 JSON
                    if lname in PRIMARY_GAME_FILENAMES:
                        break

            # 若 ZIP 内未找到 JSON 游戏数据但包含 LevelDB / PouchDB 文件，则解压到临时目录走同一套 LevelDB 解析逻辑
            if not game_pairs and has_leveldb_in_zip:
                with tempfile.TemporaryDirectory(prefix="tsumugi_vnite_zip_") as tmp_zip_dir:
                    extracted_root = Path(tmp_zip_dir)
                    _safe_extract_zip(zf, extracted_root)
                    return self._scan_leveldb_root(
                        extracted_root,
                        staging_key=f"zip:{zip_file.resolve()}",
                        extra_img_index=img_index,
                    )

        if not game_pairs:
            raise ImporterError(
                f"在 ZIP 备份 {zip_file.name} 中未找到可解析的 Vnite 游戏数据（JSON 或 LevelDB）"
            )

        return self._build_candidates(game_pairs, locals_map, img_index, base_dir=zip_file.parent)

    def _scan_leveldb_root(
        self,
        root_dir: Path,
        *,
        staging_key: str,
        extra_img_index: dict[str, dict[str, str]] | None = None,
    ) -> list[ExternalGameCandidate]:
        """递归扫描目录下全部 LevelDB/PouchDB 子库，按 _id 跨库合并元数据、本地路径与二进制图片附件"""
        ldb_dirs = discover_leveldb_directories(root_dir)
        if not ldb_dirs:
            raise ImporterError(
                f"在所选目录中未发现 Vnite LevelDB 子库或 JSON 数据文件，请确认路径正确或选择 .json / .zip 备份文件。"
            )

        parsed_results: list[PouchDBParseResult] = []
        games_by_id: dict[str, dict[str, Any]] = {}
        locals_map: dict[str, dict[str, Any]] = {}

        for sub_dir in ldb_dirs:
            try:
                rel_name = sub_dir.relative_to(root_dir).as_posix()
            except ValueError:
                rel_name = sub_dir.name
            subdb_label = sub_dir.name if rel_name == "." else rel_name
            parsed = parse_pouchdb_directory(sub_dir, subdb_name=subdb_label)
            parsed_results.append(parsed)

            leaf = sub_dir.name.lower()
            if leaf in _LOCAL_SUBDB_NAMES:
                for doc_id, doc in parsed.documents.items():
                    locals_map[doc_id] = _deep_merge_docs(locals_map.get(doc_id, {}), doc)
                continue

            if leaf in _ATTACHMENT_SUBDB_NAMES or leaf in _IGNORED_GAME_SUBDB_NAMES:
                continue

            for doc_id, doc in parsed.documents.items():
                if _looks_like_game_doc(doc):
                    games_by_id[doc_id] = _deep_merge_docs(games_by_id.get(doc_id, {}), doc)
                elif _looks_like_local_doc(doc):
                    locals_map[doc_id] = _deep_merge_docs(locals_map.get(doc_id, {}), doc)

        # 将同一游戏 _id 在 game-local 等子库中的字段合并回主文档，同时保留 locals_map
        for doc_id, local_doc in locals_map.items():
            if doc_id in games_by_id:
                games_by_id[doc_id] = _deep_merge_docs(games_by_id[doc_id], local_doc)

        if not games_by_id:
            diag_parts: list[str] = []
            subdb_names: list[str] = []
            for p in parsed_results:
                subdb_names.append(p.subdb_name)
                sample_keys = [
                    sorted(str(k) for k in doc.keys())[:10]
                    for doc in list(p.documents.values())[:3]
                ]
                diag_parts.append(
                    f"{p.subdb_name}(kv={p.raw_entry_count}, docs={len(p.documents)}, "
                    f"sublevels={p.sublevels}, sample_keys={sample_keys})"
                )
            logger.warning(
                "Vnite LevelDB scan produced 0 game records | subdbs=%s",
                "; ".join(diag_parts),
            )
            sub_summary = "、".join(subdb_names[:6]) if subdb_names else "无"
            raise ImporterError(
                f"已只读解析 Vnite LevelDB 目录（发现子库：{sub_summary}），但未识别到有效游戏记录。"
                "请确认所选目录为 Vnite 的 database 目录（如 ...\\vnite\\app\\database），"
                "或改选 Vnite 导出的 .json / .zip 备份文件；详细诊断已写入 data/tsumugi.log。"
            )

        # 构建图片索引：优先提取 PouchDB 内嵌二进制附件，其次合并本地目录/ZIP 图片索引
        known_game_ids = {gid.lower() for gid in games_by_id}
        pouch_img_index: dict[str, dict[str, str]] = {}
        fallback_other_index: dict[str, str] = {}
        fallback_icon_index: dict[str, str] = {}
        stage_dir: Path | None = None

        def _ensure_stage_dir() -> Path:
            nonlocal stage_dir
            if stage_dir is None:
                stage_dir = _prepare_attachment_staging_dir(staging_key)
            return stage_dir

        for parsed in parsed_results:
            if not parsed.attachments_by_digest and not any(
                isinstance(d.get("_attachments"), dict) and d.get("_attachments")
                for d in parsed.documents.values()
            ):
                continue

            for doc_id, doc in parsed.documents.items():
                attachments = doc.get("_attachments")
                if not isinstance(attachments, dict) or not attachments:
                    continue
                gid_lower = (
                    doc_id.lower()
                    if doc_id.lower() in known_game_ids
                    else _extract_game_id_from_attachment_doc_id(doc_id, known_game_ids)
                )
                if not gid_lower:
                    continue

                bucket = pouch_img_index.setdefault(gid_lower, {})
                for att_name, att_meta in attachments.items():
                    if not isinstance(att_meta, dict):
                        continue
                    raw_bytes = _extract_attachment_bytes_from_meta(att_meta, parsed.attachments_by_digest)
                    if not raw_bytes:
                        continue
                    role = _resolve_attachment_role(str(att_name), doc_id)
                    ct = str(att_meta.get("content_type") or "")
                    if role == "cover" and "cover" not in bucket:
                        bucket["cover"] = _write_staged_attachment(
                            _ensure_stage_dir(),
                            gid_lower,
                            "cover",
                            raw_bytes,
                            content_type=ct,
                            filename=str(att_name),
                        )
                    elif role == "background" and "background" not in bucket:
                        bucket["background"] = _write_staged_attachment(
                            _ensure_stage_dir(),
                            gid_lower,
                            "background",
                            raw_bytes,
                            content_type=ct,
                            filename=str(att_name),
                        )
                    elif role == "other" and gid_lower not in fallback_other_index:
                        fallback_other_index[gid_lower] = _write_staged_attachment(
                            _ensure_stage_dir(),
                            gid_lower,
                            "cover_alt",
                            raw_bytes,
                            content_type=ct,
                            filename=str(att_name),
                        )
                    elif role == "icon" and gid_lower not in fallback_icon_index:
                        fallback_icon_index[gid_lower] = _write_staged_attachment(
                            _ensure_stage_dir(),
                            gid_lower,
                            "icon",
                            raw_bytes,
                            content_type=ct,
                            filename=str(att_name),
                        )

            # 兜底：若 attach 子表中有指向某游戏的二进制图片但未在 _attachments 中显式命中
            for digest, ref_doc_ids in parsed.attachment_refs.items():
                raw_bytes = parsed.attachments_by_digest.get(digest)
                if not raw_bytes:
                    continue
                for ref_doc_id in ref_doc_ids:
                    gid_lower = _extract_game_id_from_attachment_doc_id(ref_doc_id, known_game_ids)
                    if not gid_lower:
                        continue
                    bucket = pouch_img_index.setdefault(gid_lower, {})
                    if "cover" not in bucket and gid_lower not in fallback_other_index:
                        fallback_other_index[gid_lower] = _write_staged_attachment(
                            _ensure_stage_dir(),
                            gid_lower,
                            "cover_ref",
                            raw_bytes,
                        )

        for gid_lower, alt_path in fallback_other_index.items():
            pouch_img_index.setdefault(gid_lower, {}).setdefault("cover", alt_path)
        for gid_lower, icon_path in fallback_icon_index.items():
            pouch_img_index.setdefault(gid_lower, {}).setdefault("cover", icon_path)

        # 合并文件系统图片索引与可选 ZIP 图片索引（PouchDB 内嵌附件优先，本地目录图片补全缺失项）
        merged_img_index: dict[str, dict[str, str]] = {}
        for src_index in (pouch_img_index, _index_directory_images(root_dir), extra_img_index or {}):
            for gid_lower, roles in src_index.items():
                bucket = merged_img_index.setdefault(gid_lower, {})
                for role_key in ("cover", "background"):
                    if role_key not in bucket and roles.get(role_key):
                        bucket[role_key] = roles[role_key]

        game_pairs = list(games_by_id.items())
        return self._build_candidates(game_pairs, locals_map, merged_img_index, base_dir=root_dir)

    def _scan_directory(self, root_dir: Path) -> list[ExternalGameCandidate]:
        game_pairs: list[tuple[str, dict[str, Any]]] = []
        locals_map: dict[str, dict[str, Any]] = {}

        # 收集目录中（含常见子目录）的 JSON 文件
        search_dirs = [root_dir]
        for sub in ("app/database", "database", "app", "export", "backup"):
            cand = root_dir / sub
            if cand.is_dir() and cand not in search_dirs:
                search_dirs.append(cand)

        # 读取 local 路径映射
        for d in search_dirs:
            for lname in LOCAL_META_FILENAMES:
                lf = d / lname
                if lf.is_file():
                    try:
                        locals_map.update(_parse_local_doc_map(json.loads(lf.read_text(encoding="utf-8-sig"))))
                    except Exception:
                        pass
            local_sub = d / "game-local"
            if local_sub.is_dir():
                for jf in sorted(local_sub.glob("*.json")):
                    try:
                        parsed = json.loads(jf.read_text(encoding="utf-8-sig"))
                        if isinstance(parsed, dict):
                            lid = str(parsed.get("_id") or parsed.get("id") or jf.stem).strip()
                            locals_map[lid] = parsed
                    except Exception:
                        pass

        # 优先查找主 games.json / game.json / backup.json
        for d in search_dirs:
            for fname in PRIMARY_GAME_FILENAMES:
                gf = d / fname
                if not gf.is_file():
                    continue
                try:
                    parsed = json.loads(gf.read_text(encoding="utf-8-sig"))
                except Exception:
                    continue
                extracted, ex_locals = _extract_games_and_locals_from_json(parsed)
                if ex_locals:
                    locals_map.update(ex_locals)
                if extracted:
                    game_pairs.extend(extracted)
                    break
            if game_pairs:
                break

        # 若没有汇总文件，尝试读取 games/*.json 或 game/*.json 单条文件
        if not game_pairs:
            for d in search_dirs:
                for sub in ("games", "game"):
                    gdir = d / sub
                    if not gdir.is_dir():
                        continue
                    for jf in sorted(gdir.glob("*.json")):
                        try:
                            parsed = json.loads(jf.read_text(encoding="utf-8-sig"))
                        except Exception:
                            continue
                        extracted, ex_locals = _extract_games_and_locals_from_json(parsed)
                        if ex_locals:
                            locals_map.update(ex_locals)
                        if extracted:
                            game_pairs.extend(extracted)
                if game_pairs:
                    break

        if not game_pairs:
            # 未找到 JSON 导出文件时，自动直读本地 LevelDB / PouchDB 子库
            if _has_leveldb_files(root_dir) or discover_leveldb_directories(root_dir):
                return self._scan_leveldb_root(root_dir, staging_key=str(root_dir.resolve()))
            raise ImporterError(
                f"在目录 {root_dir} 中未找到 Vnite LevelDB 数据库或 JSON 游戏数据文件，"
                "请确认路径正确或选择 Vnite 导出的 .json / .zip 备份文件。"
            )

        img_index = _index_directory_images(root_dir)
        return self._build_candidates(game_pairs, locals_map, img_index, base_dir=root_dir)

    def _build_candidates(
        self,
        game_pairs: list[tuple[str, dict[str, Any]]],
        locals_map: dict[str, dict[str, Any]],
        img_index: dict[str, dict[str, str]],
        base_dir: Path,
    ) -> list[ExternalGameCandidate]:
        candidates: list[ExternalGameCandidate] = []
        seen_ids: set[str] = set()

        for raw_id, doc in game_pairs:
            ext_id = str(doc.get("_id") or doc.get("id") or raw_id).strip()
            if not ext_id or ext_id in seen_ids:
                continue

            meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
            record = doc.get("record") if isinstance(doc.get("record"), dict) else {}
            local_doc = locals_map.get(ext_id, {})

            name = str(
                meta.get("name") or doc.get("name") or doc.get("title") or meta.get("originalName") or ""
            ).strip()
            if not name:
                continue
            seen_ids.add(ext_id)

            original_name = str(
                meta.get("originalName")
                or doc.get("originalName")
                or doc.get("original_name")
                or doc.get("sub_title")
                or ""
            ).strip()
            if original_name.lower() == name.lower():
                original_name = ""

            raw_desc = meta.get("description") or doc.get("description") or doc.get("synopsis") or ""
            description = clean_html_description(str(raw_desc))

            release_date = _normalize_release_date(
                meta.get("releaseDate") or doc.get("releaseDate") or doc.get("release_date")
            )

            developers = _to_str_list(
                meta.get("developers")
                or meta.get("developer")
                or doc.get("developers")
                or doc.get("developer")
            )
            publishers = _to_str_list(
                meta.get("publishers")
                or meta.get("publisher")
                or doc.get("publishers")
                or doc.get("publisher")
            )

            tags_raw = [
                *_to_str_list(meta.get("genres") or doc.get("genres")),
                *_to_str_list(meta.get("tags") or doc.get("tags")),
            ]
            tags: list[str] = []
            seen_t: set[str] = set()
            for t in tags_raw:
                low = t.lower()
                if low not in seen_t:
                    seen_t.add(low)
                    tags.append(t)

            playtime_seconds = normalize_vnite_playtime_seconds(doc, record)
            last_played = _parse_iso_datetime(
                record.get("lastRunDate")
                or record.get("lastPlayedAt")
                or doc.get("lastRunDate")
                or doc.get("lastPlayedAt")
                or doc.get("last_played_at")
            )
            play_status = _map_vnite_status(
                record.get("playStatus") or doc.get("playStatus") or doc.get("status"),
                playtime_seconds,
            )

            # 提取外部 ID（直接字段 + externalIds + relatedSites/links 兜底）
            ext_id_bag = (
                meta.get("externalIds")
                if isinstance(meta.get("externalIds"), dict)
                else (doc.get("externalIds") if isinstance(doc.get("externalIds"), dict) else {})
            )
            site_steam, site_vndb, site_bgm, site_ymgal = _extract_ids_from_sites(
                meta.get("relatedSites") or doc.get("relatedSites") or doc.get("links")
            )
            vndb_id = (
                _normalize_vndb(
                    meta.get("vndbId")
                    or meta.get("vndb_id")
                    or ext_id_bag.get("vndb")
                    or doc.get("vndbId")
                    or doc.get("vndb_id")
                    or doc.get("vndb")
                )
                or site_vndb
            )
            bangumi_id = (
                _normalize_digits(
                    meta.get("bangumiId")
                    or meta.get("bgmId")
                    or meta.get("bangumi_id")
                    or ext_id_bag.get("bangumi")
                    or ext_id_bag.get("bgm")
                    or doc.get("bangumiId")
                    or doc.get("bgmId")
                    or doc.get("bangumi_id")
                    or doc.get("bgm")
                )
                or site_bgm
            )
            steam_appid = (
                _normalize_digits(
                    meta.get("steamId")
                    or meta.get("steamAppId")
                    or ext_id_bag.get("steam")
                    or doc.get("steamId")
                    or doc.get("steamAppId")
                    or doc.get("steam_appid")
                    or doc.get("steam")
                )
                or site_steam
            )
            ymgal_id = (
                _normalize_ymgal(
                    meta.get("ymgalId")
                    or meta.get("ymgal_id")
                    or ext_id_bag.get("ymgal")
                    or doc.get("ymgalId")
                    or doc.get("ymgal_id")
                    or doc.get("ymgal")
                )
                or site_ymgal
            )

            # 启动路径（优先 local_doc，其次 doc.path / doc.launcher / 扁平字段）
            executable_path = self._extract_game_path(doc, local_doc)
            install_dir = str(Path(executable_path).parent) if executable_path and not executable_path.startswith(("http://", "https://", "steam://")) else ""

            # 本地封面与背景图定位（支持显式字段 + PouchDB 二进制附件 + 本地目录或 ZIP 成员）
            cover_path, background_path = self._resolve_images(ext_id, doc, img_index, base_dir)

            platforms = _to_str_list(meta.get("platforms") or doc.get("platforms"))
            platform_source = platforms[0] if platforms else ("Steam" if steam_appid else "Vnite")

            candidates.append(
                ExternalGameCandidate(
                    external_id=ext_id,
                    source_app="vnite",
                    name=name,
                    original_name=original_name,
                    description=description,
                    release_date=release_date,
                    developers=developers,
                    publishers=publishers,
                    tags=tags,
                    playtime_seconds=playtime_seconds,
                    last_played_at=last_played,
                    play_status=play_status,
                    platform_source=platform_source,
                    steam_appid=steam_appid,
                    vndb_id=vndb_id,
                    bangumi_id=bangumi_id,
                    ymgal_id=ymgal_id,
                    install_dir=install_dir,
                    executable_path=executable_path,
                    cover_path=cover_path,
                    background_path=background_path,
                )
            )

        candidates.sort(key=lambda item: (item.name.lower(), item.external_id))
        return candidates

    def _extract_game_path(self, doc: dict[str, Any], local_doc: dict[str, Any]) -> str:
        for container in (local_doc, doc):
            if not isinstance(container, dict):
                continue
            path_obj = container.get("path")
            if isinstance(path_obj, dict):
                gp = str(path_obj.get("gamePath") or path_obj.get("exePath") or "").strip()
                if gp:
                    return gp
            launcher = container.get("launcher")
            if isinstance(launcher, dict):
                fc = launcher.get("fileConfig")
                if isinstance(fc, dict):
                    fp = str(fc.get("path") or "").strip()
                    if fp:
                        return fp
                uc = launcher.get("urlConfig")
                if isinstance(uc, dict):
                    up = str(uc.get("url") or "").strip()
                    if up:
                        return up
            for flat_key in ("gamePath", "game_path", "exePath", "exe_path", "executablePath"):
                val = str(container.get(flat_key) or "").strip()
                if val:
                    return val
        return ""

    def _resolve_images(
        self,
        ext_id: str,
        doc: dict[str, Any],
        img_index: dict[str, dict[str, str]],
        base_dir: Path,
    ) -> tuple[str, str]:
        cover_path = ""
        bg_path = ""

        def _check_explicit(raw_ref: Any) -> str:
            ref = str(raw_ref or "").strip()
            if not ref or ref.lower().startswith(("http://", "https://", "data:")):
                return ""
            if ref.startswith(ZIP_URI_PREFIX):
                return ref
            p = Path(ref)
            if p.is_file():
                return str(p.resolve())
            rel = base_dir / Path(*[seg for seg in ref.replace("\\", "/").split("/") if seg])
            if rel.is_file():
                return str(rel.resolve())
            return ""

        media_obj = doc.get("media") if isinstance(doc.get("media"), dict) else {}
        for k in ("coverPath", "cover_path", "cover", "coverImage"):
            cover_path = _check_explicit(doc.get(k) or media_obj.get(k))
            if cover_path:
                break

        for k in ("backgroundPath", "background_path", "background", "backgroundImage", "heroPath"):
            bg_path = _check_explicit(doc.get(k) or media_obj.get(k))
            if bg_path:
                break

        indexed = img_index.get(ext_id.lower(), {})
        if not cover_path and indexed.get("cover"):
            cover_path = indexed["cover"]
        if not bg_path and indexed.get("background"):
            bg_path = indexed["background"]

        return cover_path, bg_path
