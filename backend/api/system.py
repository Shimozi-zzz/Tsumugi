import asyncio
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
import httpx
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.background import BackgroundTask

from backend.api.settings import DEFAULT_SETTINGS, SOURCE_TOKEN_LINKS
from backend.core.config import (
    APP_VERSION,
    ASSETS_DIR,
    BACKUPS_DIR,
    DATA_DIR,
    GITHUB_REPO,
    THUMBS_CACHE_DIR,
    THUMBS_DIR,
    WALLPAPERS_DIR,
)
from backend.core.scraper_settings import (
    load_scraper_settings,
    mask_scraper_settings_for_client,
    save_scraper_settings,
)
from backend.db.database import engine, get_db, init_db
from backend.db.models import AppStateSetting, Game
from backend.schemas import ScraperSettingsUpdateRequest
from backend.scrapers.manager import ScraperManager
from backend.services.backup_service import (
    default_backup_zip_filename,
    export_library_backup_zip,
    list_auto_snapshots,
    restore_database_from_snapshot,
    restore_library_from_zip,
)
from backend.services.media_service import convert_image_to_webp, generate_cover_thumbnail
from backend.services.process_tracker import process_tracker
from backend.services.task_manager import task_manager
from backend.services.thumbnail_service import clear_thumbnail_cache

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


@router.get("/scraper-settings")
async def get_scraper_settings_endpoint(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """读取 DATA_DIR/settings.json 中的多源刮削开关与脱敏凭证配置"""
    rows = (await db.execute(select(AppStateSetting))).scalars().all()
    db_cfg = {**DEFAULT_SETTINGS, **{row.key: row.value for row in rows}}
    raw_cfg = load_scraper_settings(db_cfg=db_cfg)
    manager = ScraperManager(
        proxy_url=str(db_cfg.get("proxy_url") or ""),
        allow_nsfw=bool(db_cfg.get("allow_nsfw_scrape", True)),
        scraper_settings=raw_cfg,
    )
    masked = mask_scraper_settings_for_client(raw_cfg)
    masked["sources"] = manager.list_source_descriptors()
    masked["source_links"] = dict(SOURCE_TOKEN_LINKS)
    return masked


@router.put("/scraper-settings")
async def update_scraper_settings_endpoint(
    payload: ScraperSettingsUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """持久化数据源开关与凭证至 DATA_DIR/settings.json（脱敏返回，不泄露明文密钥）"""
    rows = (await db.execute(select(AppStateSetting))).scalars().all()
    db_cfg = {**DEFAULT_SETTINGS, **{row.key: row.value for row in rows}}

    updates = payload.model_dump(exclude_unset=True)
    saved = save_scraper_settings(updates, db_cfg=db_cfg)

    # 同步 Bangumi Token、TouchGal API Key 与 SteamGridDB Key 至数据库 AppStateSetting 保持旧功能互通
    api_keys_row = await db.get(AppStateSetting, "api_keys")
    current_keys = (
        dict(api_keys_row.value)
        if api_keys_row and isinstance(api_keys_row.value, dict)
        else dict(DEFAULT_SETTINGS["api_keys"])
    )
    current_keys["bangumi"] = str(saved.get("bangumi_token") or "")
    current_keys["touchgal"] = str(saved.get("touchgal_api_key") or "")
    current_keys["steamgriddb"] = str(saved.get("steamgriddb_api_key") or "")
    if api_keys_row:
        api_keys_row.value = current_keys
    else:
        db.add(AppStateSetting(key="api_keys", value=current_keys))

    bgm_row = await db.get(AppStateSetting, "bangumi_token")
    if bgm_row:
        bgm_row.value = str(saved.get("bangumi_token") or "")
    else:
        db.add(AppStateSetting(key="bangumi_token", value=str(saved.get("bangumi_token") or "")))

    await db.commit()

    manager = ScraperManager(
        proxy_url=str(db_cfg.get("proxy_url") or ""),
        allow_nsfw=bool(db_cfg.get("allow_nsfw_scrape", True)),
        scraper_settings=saved,
    )
    masked = mask_scraper_settings_for_client(saved)
    masked["sources"] = manager.list_source_descriptors()
    masked["source_links"] = dict(SOURCE_TOKEN_LINKS)
    return masked


# ──────────────────── 2. 存储占用分析与孤儿文件清理 ────────────────────


@router.get("/storage")
async def get_storage_usage(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """递归扫描 DATA_DIR 并结合数据库有效 game_id，精确统计各分类磁盘占用与自动快照列表"""
    valid_game_ids = await _load_valid_game_ids(db)

    buckets: dict[str, dict[str, int]] = {
        "videos": {"bytes": 0, "files": 0},
        "audios": {"bytes": 0, "files": 0},
        "images": {"bytes": 0, "files": 0},
        "thumbs": {"bytes": 0, "files": 0},
        "backups": {"bytes": 0, "files": 0},
        "database": {"bytes": 0, "files": 0},
        "orphans": {"bytes": 0, "files": 0, "dirs": 0},
    }
    total_bytes = 0
    total_files = 0

    data_root = DATA_DIR.resolve()
    assets_root = ASSETS_DIR.resolve()
    backups_root = BACKUPS_DIR.resolve()
    thumbs_root = THUMBS_DIR.resolve()
    legacy_thumbs_root = THUMBS_CACHE_DIR.resolve()
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

        # 1. 存档备份与数据库自动快照目录
        if resolved.is_relative_to(backups_root):
            buckets["backups"]["bytes"] += size
            buckets["backups"]["files"] += 1
            total_bytes += size
            total_files += 1
            return

        # 2. 独立 WebP 缩略图缓存目录（DATA_DIR/thumbs 与旧版 data/cache/thumbs）
        if resolved.is_relative_to(thumbs_root) or resolved.is_relative_to(legacy_thumbs_root):
            if _is_temp_artifact(fpath):
                buckets["orphans"]["bytes"] += size
                buckets["orphans"]["files"] += 1
            else:
                buckets["thumbs"]["bytes"] += size
                buckets["thumbs"]["files"] += 1
            total_bytes += size
            total_files += 1
            return

        # 3. SQLite 数据库及 WAL / SHM 文件
        if resolved.parent == data_root and fname.startswith("tsumugi.db"):
            buckets["database"]["bytes"] += size
            buckets["database"]["files"] += 1
            total_bytes += size
            total_files += 1
            return

        # 4. 孤儿游戏资产目录（数据库中已无对应 game_id）
        if resolved.is_relative_to(assets_root):
            rel_assets = resolved.relative_to(assets_root)
            if len(rel_assets.parts) >= 2 and rel_assets.parts[0] not in valid_game_ids:
                buckets["orphans"]["bytes"] += size
                buckets["orphans"]["files"] += 1
                total_bytes += size
                total_files += 1
                return

        # 5. 残留下载临时文件（.part / .downloading.* / .tmp / .ytdl）
        if _is_temp_artifact(fpath):
            buckets["orphans"]["bytes"] += size
            buckets["orphans"]["files"] += 1
            total_bytes += size
            total_files += 1
            return

        # 6. 无效缓存文件
        if resolved.is_relative_to(cache_root) and suffix not in IMAGE_EXTS:
            buckets["orphans"]["bytes"] += size
            buckets["orphans"]["files"] += 1
            total_bytes += size
            total_files += 1
            return

        # 7. 正常媒体分类
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

    # 仅扫描 Tsumugi 自身管理的媒体/缩略图/缓存/备份目录（避免误扫外部残留目录）
    for managed_dir in (assets_root, backups_root, thumbs_root, cache_root, wallpapers_root):
        if not managed_dir.exists() or not managed_dir.is_dir():
            continue
        for root_str, _dirs, files in os.walk(managed_dir):
            root_path = Path(root_str)
            for fname in files:
                _record_file(root_path / fname)

    snapshots = list_auto_snapshots()

    return {
        **buckets,
        "total_bytes": total_bytes,
        "total_files": total_files,
        "db_bytes": buckets["database"]["bytes"],
        "images_bytes": buckets["images"]["bytes"],
        "videos_bytes": buckets["videos"]["bytes"],
        "audios_bytes": buckets["audios"]["bytes"],
        "thumbs_bytes": buckets["thumbs"]["bytes"],
        "backups_bytes": buckets["backups"]["bytes"],
        "snapshots": snapshots,
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


# ──────────────────── 3.5 缩略图缓存清理 & 整库一键备份/恢复/自动快照 ────────────────────


class LibraryBackupExportRequest(BaseModel):
    include_videos: bool = False
    target_path: str = ""


class SnapshotRestoreRequest(BaseModel):
    filename: str


def _safe_unlink_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


@router.post("/cache/clear-thumbs")
async def clear_thumbs_cache_endpoint() -> dict[str, Any]:
    """一键清空 DATA_DIR/thumbs/（含旧版缓存）全部缩略图，后续访问时自动按需重建"""
    stats = await asyncio.to_thread(clear_thumbnail_cache)
    return {"cleared": True, **stats}


@router.post("/backup/export")
async def export_full_library_backup(
    payload: LibraryBackupExportRequest | None = None,
):
    """
    整库一键导出 (.zip)：
    - 若传入 target_path（桌面端经原生文件保存框选定路径），直接原子落盘并返回 JSON 摘要；
    - 否则（浏览器环境）流式返回 FileResponse 触发附件下载，完成后自动清理临时包。
    """
    include_videos = bool(payload.include_videos) if payload else False
    target_raw = (payload.target_path or "").strip() if payload else ""

    if target_raw:
        if "\x00" in target_raw:
            raise HTTPException(status_code=400, detail="无效的导出路径")
        dest = Path(target_raw).expanduser()
        if dest.suffix.lower() != ".zip":
            dest = dest.with_suffix(".zip")
        try:
            summary = await asyncio.to_thread(
                export_library_backup_zip,
                dest,
                include_videos=include_videos,
            )
            return summary
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            logger.exception("Full library export to %s failed: %s", dest, exc)
            raise HTTPException(status_code=500, detail=f"导出整库备份失败: {exc}")

    download_name = default_backup_zip_filename()
    fd, tmp_name = tempfile.mkstemp(prefix="tsumugi_export_", suffix=".zip")
    os.close(fd)
    tmp_zip = Path(tmp_name)

    try:
        await asyncio.to_thread(
            export_library_backup_zip,
            tmp_zip,
            include_videos=include_videos,
        )
    except FileNotFoundError as exc:
        _safe_unlink_file(tmp_zip)
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        _safe_unlink_file(tmp_zip)
        logger.exception("Full library streaming export failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"导出整库备份失败: {exc}")

    return FileResponse(
        tmp_zip,
        media_type="application/zip",
        filename=download_name,
        background=BackgroundTask(_safe_unlink_file, tmp_zip),
    )


@router.post("/backup/restore")
async def restore_full_library_backup(request: Request) -> dict[str, Any]:
    """
    整库安全恢复：
    - 支持桌面端 JSON {"source_path": "..."} 直读本地 .zip，也支持浏览器 multipart/form-data 上传 .zip；
    - 故意不注入 AsyncSession 依赖，确保恢复期间可通过 await engine.dispose() 彻底释放 Windows SQLite 文件锁。
    """
    content_type = (request.headers.get("content-type") or "").lower()
    tmp_upload: Path | None = None
    zip_path: Path | None = None

    try:
        if "multipart/form-data" in content_type:
            form = await request.form()
            upload = form.get("file")
            source_field = str(form.get("source_path") or "").strip()
            if upload is not None and hasattr(upload, "read"):
                fd, tmp_name = tempfile.mkstemp(prefix="tsumugi_upload_", suffix=".zip")
                os.close(fd)
                tmp_upload = Path(tmp_name)
                with tmp_upload.open("wb") as out_f:
                    while True:
                        chunk = await upload.read(1024 * 1024)
                        if not chunk:
                            break
                        out_f.write(chunk)
                zip_path = tmp_upload
            elif source_field:
                zip_path = Path(source_field).expanduser()
        else:
            try:
                body = await request.json()
            except Exception:
                body = {}
            source_path = str((body or {}).get("source_path") or "").strip()
            if source_path:
                zip_path = Path(source_path).expanduser()

        if zip_path is None:
            raise HTTPException(status_code=400, detail="请提供备份文件路径或上传 .zip 备份文件")

        if process_tracker.is_running:
            await process_tracker.shutdown_flush()

        result = await restore_library_from_zip(
            zip_path,
            dispose_engine=engine.dispose,
            reinit_db=init_db,
        )
        return result
    except HTTPException:
        raise
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Full library restore failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"恢复整库备份失败: {exc}")
    finally:
        if tmp_upload is not None:
            _safe_unlink_file(tmp_upload)


@router.post("/backup/restore-snapshot")
async def restore_auto_snapshot_endpoint(payload: SnapshotRestoreRequest) -> dict[str, Any]:
    """按文件名回滚 DATA_DIR/backups/auto/ 下的指定自动数据库快照（回滚前自动保存 pre_restore 保护快照）"""
    try:
        if process_tracker.is_running:
            await process_tracker.shutdown_flush()
        return await restore_database_from_snapshot(
            payload.filename,
            dispose_engine=engine.dispose,
            reinit_db=init_db,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Snapshot rollback failed for %s: %s", payload.filename, exc)
        raise HTTPException(status_code=500, detail=f"回滚数据库快照失败: {exc}")


# ──────────────────── 4. 版本信息与 GitHub Releases 检查更新 ────────────────────

INSTALLER_ASSET_EXTS = (".exe", ".msi", ".appimage")
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
    fallback_url = ""
    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        dl_url = str(item.get("browser_download_url") or "").strip()
        if not dl_url:
            continue
        if name.endswith(".exe"):
            return dl_url
        if not fallback_url and name.endswith(INSTALLER_ASSET_EXTS):
            fallback_url = dl_url
    return fallback_url


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
