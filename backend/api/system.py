import logging
import os
from pathlib import Path
import re
import shutil
from typing import Any

from fastapi import APIRouter, Depends, Query
import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.api.settings import SOURCE_TOKEN_LINKS
from backend.core.config import (
    APP_VERSION,
    ASSETS_DIR,
    BACKUPS_DIR,
    DATA_DIR,
    GITHUB_REPO,
    THUMBS_CACHE_DIR,
    WALLPAPERS_DIR,
)
from backend.db.database import get_db
from backend.db.models import AppStateSetting, Game
from backend.services.media_service import convert_image_to_webp, generate_cover_thumbnail
from backend.services.task_manager import task_manager

logger = logging.getLogger("tsumugi.api.system")

router = APIRouter(prefix="/api/system", tags=["System"])
tasks_router = APIRouter(prefix="/api/tasks", tags=["Tasks"])

VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi"}
AUDIO_EXTS = {".m4a", ".mp3", ".flac", ".ogg", ".wav", ".opus"}
IMAGE_EXTS = {".webp", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".avif"}
LEGACY_CONVERTIBLE_EXTS = {".png", ".jpg", ".jpeg"}

CONVERTIBLE_FIELDS: tuple[tuple[str, str], ...] = (
    ("cover_path", "cover"),
    ("hero_bg_path", "hero"),
    ("logo_path", "logo"),
    ("custom_spine_path", "custom_spine"),
)


def _is_temp_artifact(path: Path) -> bool:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if suffix in (".part", ".ytdl", ".tmp"):
        return True
    if ".downloading." in name or name.endswith(".downloading"):
        return True
    return False


def _resolve_data_file(raw: str) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        p = DATA_DIR / p
    return p


async def _load_valid_game_ids(db: AsyncSession) -> set[str]:
    rows = (await db.execute(select(Game.id))).scalars().all()
    return {str(gid) for gid in rows}


# ──────────────────── 1. 数据源官方 Token 创建直达链接 ────────────────────


@router.get("/source-links")
async def get_source_token_links() -> dict[str, str]:
    """返回各第三方数据源官方 API Token / Key 申请直达链接"""
    return dict(SOURCE_TOKEN_LINKS)


# ──────────────────── 2. 存储占用分析与孤儿文件清理 ────────────────────


@router.get("/storage")
async def get_storage_usage(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """递归扫描 DATA_DIR 并结合数据库有效 game_id，精确统计各分类磁盘占用"""
    valid_game_ids = await _load_valid_game_ids(db)

    buckets: dict[str, dict[str, int]] = {
        "videos": {"bytes": 0, "files": 0},
        "audios": {"bytes": 0, "files": 0},
        "images": {"bytes": 0, "files": 0},
        "backups": {"bytes": 0, "files": 0},
        "database": {"bytes": 0, "files": 0},
        "orphans": {"bytes": 0, "files": 0, "dirs": 0},
    }
    total_bytes = 0
    total_files = 0

    data_root = DATA_DIR.resolve()
    assets_root = ASSETS_DIR.resolve()
    backups_root = BACKUPS_DIR.resolve()
    cache_root = (DATA_DIR / "cache").resolve()
    wallpapers_root = WALLPAPERS_DIR.resolve()

    if assets_root.exists() and assets_root.is_dir():
        for child in assets_root.iterdir():
            if child.is_dir() and child.name not in valid_game_ids:
                buckets["orphans"]["dirs"] += 1

    def _record_file(fpath: Path) -> None:
        nonlocal total_bytes, total_files
        if fpath.is_symlink() or not fpath.is_file():
            return
        try:
            size = fpath.stat().st_size
        except OSError:
            return

        resolved = fpath.resolve()
        fname = fpath.name
        suffix = fpath.suffix.lower()

        # 1. 存档备份目录
        if resolved.is_relative_to(backups_root):
            buckets["backups"]["bytes"] += size
            buckets["backups"]["files"] += 1
            total_bytes += size
            total_files += 1
            return

        # 2. SQLite 数据库及 WAL / SHM 文件
        if resolved.parent == data_root and fname.startswith("tsumugi.db"):
            buckets["database"]["bytes"] += size
            buckets["database"]["files"] += 1
            total_bytes += size
            total_files += 1
            return

        # 3. 孤儿游戏资产目录（数据库中已无对应 game_id）
        if resolved.is_relative_to(assets_root):
            rel_assets = resolved.relative_to(assets_root)
            if len(rel_assets.parts) >= 2 and rel_assets.parts[0] not in valid_game_ids:
                buckets["orphans"]["bytes"] += size
                buckets["orphans"]["files"] += 1
                total_bytes += size
                total_files += 1
                return

        # 4. 残留下载临时文件（.part / .downloading.* / .tmp / .ytdl）
        if _is_temp_artifact(fpath):
            buckets["orphans"]["bytes"] += size
            buckets["orphans"]["files"] += 1
            total_bytes += size
            total_files += 1
            return

        # 5. 无效缓存文件
        if resolved.is_relative_to(cache_root) and suffix not in IMAGE_EXTS:
            buckets["orphans"]["bytes"] += size
            buckets["orphans"]["files"] += 1
            total_bytes += size
            total_files += 1
            return

        # 6. 正常媒体分类
        if suffix in VIDEO_EXTS:
            buckets["videos"]["bytes"] += size
            buckets["videos"]["files"] += 1
            total_bytes += size
            total_files += 1
        elif suffix in AUDIO_EXTS:
            buckets["audios"]["bytes"] += size
            buckets["audios"]["files"] += 1
            total_bytes += size
            total_files += 1
        elif suffix in IMAGE_EXTS:
            buckets["images"]["bytes"] += size
            buckets["images"]["files"] += 1
            total_bytes += size
            total_files += 1

    # 扫描 SQLite 数据库及其 WAL / SHM 伴随文件
    if data_root.exists():
        for db_file in data_root.glob("tsumugi.db*"):
            _record_file(db_file)

    # 仅扫描 Tsumugi 自身管理的媒体/缓存/备份目录（避免误扫外部残留目录）
    for managed_dir in (assets_root, backups_root, cache_root, wallpapers_root):
        if not managed_dir.exists() or not managed_dir.is_dir():
            continue
        for root_str, _dirs, files in os.walk(managed_dir):
            root_path = Path(root_str)
            for fname in files:
                _record_file(root_path / fname)

    return {
        **buckets,
        "total_bytes": total_bytes,
        "total_files": total_files,
    }


@router.post("/storage/cleanup")
async def cleanup_orphan_storage(db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    """安全清理孤儿游戏资产目录与残留下载临时文件，绝不误删在库资产、备份或数据库"""
    valid_game_ids = await _load_valid_game_ids(db)

    deleted_files = 0
    deleted_dirs = 0
    freed_bytes = 0

    assets_root = ASSETS_DIR.resolve()
    cache_root = (DATA_DIR / "cache").resolve()

    # 1. 清理已删除游戏的孤儿目录 data/assets/{orphan_id}/
    if assets_root.exists() and assets_root.is_dir():
        for child in list(assets_root.iterdir()):
            if child.is_symlink():
                continue
            if child.is_dir():
                if child.name not in valid_game_ids:
                    dir_files = 0
                    dir_bytes = 0
                    for r, _ds, fs in os.walk(child):
                        for fname in fs:
                            fp = Path(r) / fname
                            if not fp.is_symlink():
                                try:
                                    dir_bytes += fp.stat().st_size
                                    dir_files += 1
                                except OSError:
                                    pass
                    try:
                        shutil.rmtree(child)
                        deleted_dirs += 1
                        deleted_files += dir_files
                        freed_bytes += dir_bytes
                    except OSError as exc:
                        logger.warning("Failed to remove orphan dir %s: %s", child, exc)
                else:
                    # 在库游戏目录：仅清理非活动下载的残留临时文件
                    active_download = child.name.isdigit() and task_manager.is_active(int(child.name))
                    if active_download:
                        continue
                    for r, _ds, fs in os.walk(child):
                        for fname in fs:
                            fp = Path(r) / fname
                            if fp.is_symlink() or not _is_temp_artifact(fp):
                                continue
                            try:
                                sz = fp.stat().st_size
                                fp.unlink()
                                deleted_files += 1
                                freed_bytes += sz
                            except OSError:
                                pass
            elif child.is_file() and _is_temp_artifact(child):
                try:
                    sz = child.stat().st_size
                    child.unlink()
                    deleted_files += 1
                    freed_bytes += sz
                except OSError:
                    pass

    # 2. 清理缓存目录中的临时文件与无效非图片缓存
    if cache_root.exists() and cache_root.is_dir():
        for r, _ds, fs in os.walk(cache_root):
            for fname in fs:
                fp = Path(r) / fname
                if fp.is_symlink():
                    continue
                if _is_temp_artifact(fp) or fp.suffix.lower() not in IMAGE_EXTS:
                    try:
                        sz = fp.stat().st_size
                        fp.unlink()
                        deleted_files += 1
                        freed_bytes += sz
                    except OSError:
                        pass

    return {
        "deleted_files": deleted_files,
        "deleted_dirs": deleted_dirs,
        "freed_bytes": freed_bytes,
    }


# ──────────────────── 3. 存量资产一键 WebP 压缩与缩略图兜底 ────────────────────


@router.post("/storage/convert-webp")
async def convert_existing_assets_to_webp(db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    """
    扫描数据库中所有游戏已落盘的旧 .png/.jpg/.jpeg 资产，原地转换为 .webp，
    校验新文件合法后删除旧图并同步更新数据库路径与缺失的 cover_thumb_path。
    """
    stmt = select(Game).options(selectinload(Game.media))
    games = list((await db.execute(stmt)).scalars().all())

    converted_count = 0
    skipped_count = 0
    net_saved_bytes = 0
    data_root = DATA_DIR.resolve()

    for game in games:
        media = game.media
        if not media:
            continue

        for field_name, asset_type in CONVERTIBLE_FIELDS:
            raw_path = (getattr(media, field_name) or "").strip()
            if not raw_path:
                continue

            src_file = _resolve_data_file(raw_path)
            if not src_file.exists() or not src_file.is_file():
                skipped_count += 1
                continue

            suffix = src_file.suffix.lower()
            if suffix not in LEGACY_CONVERTIBLE_EXTS:
                skipped_count += 1
                continue

            try:
                raw_bytes = src_file.read_bytes()
                old_size = len(raw_bytes)
                webp_bytes, out_ext = convert_image_to_webp(raw_bytes, asset_type)

                target_file = src_file.parent / f"{asset_type}{out_ext}"
                tmp_file = src_file.parent / f"{asset_type}.converting{out_ext}"
                tmp_file.write_bytes(webp_bytes)

                # 校验新生成的 WebP 文件可读且非空后，再原子替换并删除旧原图
                if tmp_file.stat().st_size <= 0:
                    tmp_file.unlink(missing_ok=True)
                    skipped_count += 1
                    continue
                with Image.open(tmp_file) as verify_img:
                    verify_img.verify()

                os.replace(tmp_file, target_file)
                new_size = target_file.stat().st_size

                rel_target = target_file.resolve().relative_to(data_root).as_posix()
                setattr(media, field_name, rel_target)

                if src_file.resolve() != target_file.resolve():
                    try:
                        src_file.unlink()
                    except OSError:
                        pass

                converted_count += 1
                net_saved_bytes += old_size - new_size
            except Exception as exc:
                logger.warning(
                    "WebP conversion skipped for game_id=%s %s (%s): %s",
                    game.id,
                    field_name,
                    src_file,
                    exc,
                )
                skipped_count += 1

        # 为所有具备有效封面的游戏补齐缺失的 420px cover_thumb.webp
        cover_rel = (media.cover_path or "").strip()
        if cover_rel:
            cover_file = _resolve_data_file(cover_rel)
            thumb_rel = (media.cover_thumb_path or "").strip()
            thumb_ok = bool(thumb_rel and _resolve_data_file(thumb_rel).is_file())
            if cover_file.exists() and cover_file.is_file() and not thumb_ok:
                try:
                    media.cover_thumb_path = generate_cover_thumbnail(
                        cover_file, cover_file.parent
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed generating cover_thumb for game_id=%s: %s", game.id, exc
                    )

    await db.commit()
    return {
        "converted_count": converted_count,
        "saved_bytes": max(0, net_saved_bytes),
        "skipped_count": skipped_count,
    }


# ──────────────────── 4. 版本信息与 GitHub Releases 检查更新 ────────────────────

INSTALLER_ASSET_EXTS = (".exe", ".zip", ".msi", ".appimage")
_PRERELEASE_RANKS = {
    "dev": 0,
    "alpha": 1,
    "a": 1,
    "beta": 2,
    "b": 2,
    "rc": 3,
}


def _parse_version(tag: str) -> tuple[int, ...]:
    """
    解析语义化版本标签为可比较整数元组：
    - 去除首部 v/V 与 build 元数据（+...）
    - 主体补齐至少 3 段（major, minor, patch）
    - 第 4 位标记正式版(1) / 预发布版(0)，确保正式版始终大于同主体的预发布版
    """
    cleaned = (tag or "").strip().lstrip("vV")
    if not cleaned:
        return (0, 0, 0, 1)

    cleaned = cleaned.split("+", 1)[0]
    if "-" in cleaned:
        core_part, pre_part = cleaned.split("-", 1)
        is_prerelease = True
    else:
        core_part, pre_part = cleaned, ""
        is_prerelease = False

    core_nums = [int(n) for n in re.findall(r"\d+", core_part)]
    if not core_nums:
        core_nums = [0]
    while len(core_nums) < 3:
        core_nums.append(0)

    if not is_prerelease:
        return tuple(core_nums) + (1,)

    pre_lower = pre_part.lower()
    stage_rank = 0
    for label, rank in _PRERELEASE_RANKS.items():
        if re.search(rf"(?<![a-z]){label}(?![a-z])", pre_lower):
            stage_rank = rank
            break
    pre_nums = [int(n) for n in re.findall(r"\d+", pre_part)]
    return tuple(core_nums) + (0, stage_rank) + tuple(pre_nums)


def _pick_installer_asset_url(assets: Any) -> str:
    if not isinstance(assets, list):
        return ""
    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        dl_url = str(item.get("browser_download_url") or "").strip()
        if dl_url and name.endswith(INSTALLER_ASSET_EXTS):
            return dl_url
    return ""


async def _load_proxy_url(db: AsyncSession) -> str:
    setting = await db.get(AppStateSetting, "proxy_url")
    if not setting or not setting.value:
        return ""
    return str(setting.value).strip()


@router.get("/version")
async def get_app_version() -> dict[str, str]:
    """纯本地返回当前应用版本与 GitHub 仓库地址（零外网开销）"""
    return {
        "current_version": APP_VERSION,
        "github_repo": GITHUB_REPO,
        "repo_url": f"https://github.com/{GITHUB_REPO}",
    }


@router.get("/check-update")
async def check_github_update(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """按需请求 GitHub Releases API 检查是否存在新版本，统一以 HTTP 200 返回结构化状态"""
    releases_page_url = f"https://github.com/{GITHUB_REPO}/releases"
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    proxy_url = await _load_proxy_url(db)

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"Tsumugi/{APP_VERSION}",
    }

    try:
        async with httpx.AsyncClient(
            proxy=proxy_url or None,
            timeout=10.0,
            follow_redirects=True,
        ) as client:
            resp = await client.get(api_url, headers=headers)
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("GitHub update check failed (%s): %s", GITHUB_REPO, exc)
        return {
            "status": "error",
            "current_version": APP_VERSION,
            "release_url": releases_page_url,
            "message": "无法连接 GitHub，请检查网络或代理设置",
        }

    if resp.status_code == 404:
        return {
            "status": "not_published",
            "current_version": APP_VERSION,
            "release_url": releases_page_url,
            "message": "暂未检测到公开版本",
        }

    if resp.status_code in (403, 429):
        return {
            "status": "rate_limited",
            "current_version": APP_VERSION,
            "release_url": releases_page_url,
            "message": "GitHub 请求受限，请稍后再试",
        }

    if resp.status_code != 200:
        return {
            "status": "error",
            "current_version": APP_VERSION,
            "release_url": releases_page_url,
            "message": f"检查更新失败（HTTP {resp.status_code}）",
        }

    try:
        data = resp.json()
    except ValueError:
        return {
            "status": "error",
            "current_version": APP_VERSION,
            "release_url": releases_page_url,
            "message": "GitHub 响应解析失败",
        }

    raw_tag = str(data.get("tag_name") or "").strip()
    latest_version = raw_tag.lstrip("vV") or APP_VERSION
    release_name = str(data.get("name") or raw_tag or f"v{latest_version}").strip()
    release_notes = str(data.get("body") or "").strip()
    published_at = str(data.get("published_at") or "").strip()
    release_url = str(data.get("html_url") or releases_page_url).strip()
    download_url = _pick_installer_asset_url(data.get("assets"))

    has_update = _parse_version(raw_tag or latest_version) > _parse_version(APP_VERSION)
    if has_update:
        return {
            "status": "update_available",
            "current_version": APP_VERSION,
            "latest_version": latest_version,
            "release_name": release_name,
            "release_notes": release_notes,
            "published_at": published_at,
            "release_url": release_url,
            "download_url": download_url,
            "message": f"发现新版本 v{latest_version}",
        }

    return {
        "status": "up_to_date",
        "current_version": APP_VERSION,
        "latest_version": latest_version,
        "release_name": release_name,
        "release_notes": release_notes,
        "published_at": published_at,
        "release_url": release_url,
        "download_url": download_url,
        "message": "当前已是最新版本",
    }


# ──────────────────── 5. 后台下载任务状态查询 ────────────────────


@tasks_router.get("/downloads")
async def list_download_tasks(
    game_id: int | None = Query(None, description="可选：按游戏 ID 筛选后台下载任务"),
) -> dict[str, Any]:
    """查询后台 PV / BGM 下载任务状态与实时进度"""
    items = task_manager.list_tasks(game_id=game_id)
    return {"count": len(items), "items": items}
