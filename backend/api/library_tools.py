from collections import Counter
import os
from pathlib import Path
import string
import sys
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.api.settings import DEFAULT_SETTINGS
from backend.core.os_adapter import os_adapter
from backend.core.scraper_settings import load_scraper_settings
from backend.db.database import get_db
from backend.db.models import AppStateSetting, Game, GameMediaPath, PlayRecord
from backend.schemas import (
    BackupCreateRequest,
    BatchImportRequest,
    BatchScanRequest,
    BrowsePathRequest,
    StopRunningRequest,
    ValidatePathRequest,
)
from backend.scrapers.aggregator import MetadataAggregator
from backend.scrapers.base import normalize_platform_badge
from backend.services.asset_downloader import download_game_assets
from backend.services.backup_service import (
    create_save_backup,
    delete_save_backup,
    list_save_backups,
    restore_save_backup,
)
from backend.services.batch_scanner import scan_game_directory
from backend.services.media_service import generate_pinyin_initials
from backend.services.process_tracker import process_tracker

router = APIRouter(prefix="/api/library", tags=["LibraryTools"])


# ──────────────────── 1. 实时运行状态轮询与停止 ────────────────────


@router.get("/running")
async def get_running_status() -> dict[str, Any]:
    """查询当前运行中游戏的实时状态与精确计时（前端轮询接口）"""
    return process_tracker.get_status()


@router.post("/running/stop")
async def stop_running_game(
    payload: StopRunningRequest | None = None,
) -> dict[str, Any]:
    """
    结束当前运行会话并落盘游玩时长：
    - Linux 模拟环境：模拟游戏退出、触发落盘并返回详情页；
    - Windows 生产环境：停止追踪（可选结束进程）并落盘。
    """
    terminate = bool(payload.terminate_process) if payload else False
    return await process_tracker.stop_tracking(terminate_process=terminate)


# ──────────────────── 2. 本地目录批量扫描与批量入库 ────────────────────


@router.post("/scan-directory")
async def scan_directory(
    payload: BatchScanRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """扫描目标根目录一级子目录，自动过滤干扰 .exe 并返回候选导入清单"""
    stmt = select(Game).options(selectinload(Game.media))
    existing_games = list((await db.execute(stmt)).scalars().all())
    existing_exes = {g.media.exe_path for g in existing_games if g.media and g.media.exe_path}
    existing_titles = {g.title for g in existing_games if g.title}

    try:
        candidates = scan_game_directory(
            payload.root_dir,
            existing_exes=existing_exes,
            existing_titles=existing_titles,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "root_dir": payload.root_dir,
        "count": len(candidates),
        "items": [c.model_dump() for c in candidates],
    }


@router.post("/batch-import")
async def batch_import_games(
    payload: BatchImportRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """批量导入扫描出的本地游戏（支持可选自动并发刮削元数据与视觉资产）"""
    if not payload.items:
        return {"imported_count": 0, "games": []}

    settings_rows = (await db.execute(select(AppStateSetting))).scalars().all()
    cfg = {**DEFAULT_SETTINGS, **{row.key: row.value for row in settings_rows}}
    proxy_url = str(cfg.get("proxy_url") or "")
    api_keys = cfg.get("api_keys") if isinstance(cfg.get("api_keys"), dict) else {}
    allow_nsfw = bool(cfg.get("allow_nsfw_scrape", True))

    aggregator = MetadataAggregator(
        proxy_url=proxy_url,
        api_keys=api_keys,
        allow_nsfw=allow_nsfw,
        scraper_settings=load_scraper_settings(db_cfg=cfg),
    )

    imported_ids: list[int] = []
    errors: list[dict[str, str]] = []

    for item in payload.items:
        try:
            scraped_item = None
            matched_sources: list[str] = []
            if payload.auto_scrape:
                agg = await aggregator.aggregate_detail(keyword=item.title)
                if agg["matched_sources"]:
                    scraped_item = agg["item"]
                    matched_sources = agg["matched_sources"]

            final_title = (
                scraped_item.title
                if scraped_item and scraped_item.title
                else item.title.strip()
            )
            game = Game(
                title=final_title,
                sub_title=scraped_item.sub_title if scraped_item else "",
                pinyin_initials=generate_pinyin_initials(final_title),
                developer=scraped_item.developer if scraped_item else "",
                publisher=scraped_item.publisher if scraped_item else "",
                release_date=scraped_item.release_date if scraped_item else "",
                synopsis=scraped_item.synopsis if scraped_item else "",
                tags=scraped_item.tags if scraped_item else [],
                status="todo",
                edition=item.edition or "collector",
                is_nsfw=scraped_item.is_nsfw if scraped_item else False,
                source_platform=normalize_platform_badge(
                    scraped_item.source if (scraped_item and matched_sources) else "PC",
                    scraped_item.extra_ids if scraped_item else None,
                ),
                bangumi_id=(
                    str(
                        scraped_item.bangumi_id
                        or (scraped_item.extra_ids or {}).get("bgm")
                        or (scraped_item.extra_ids or {}).get("bangumi")
                        or ""
                    ).strip()
                    if scraped_item
                    else ""
                ),
                external_ids=scraped_item.extra_ids if scraped_item else {},
                locked_fields=[],
            )
            game.media = GameMediaPath(
                exe_path=item.exe_path.strip(),
                launch_mode=item.launch_mode or "direct",
                save_dir=item.save_dir.strip(),
                screenshot_dir=item.screenshot_dir.strip(),
                pv_url_or_path=scraped_item.pv_url if scraped_item else "",
            )
            game.play_record = PlayRecord(total_seconds=0)

            db.add(game)
            await db.flush()

            if scraped_item:
                downloaded = await download_game_assets(
                    game_id=game.id,
                    cover_url=scraped_item.cover_url,
                    logo_url=scraped_item.logo_url,
                    hero_bg_url=scraped_item.hero_bg_url,
                    pv_url=scraped_item.pv_url,
                    screenshots=scraped_item.screenshots,
                    proxy_url=proxy_url,
                    download_screenshots=not bool(item.screenshot_dir.strip()),
                    max_screenshots=6,
                )
                if downloaded.get("cover_path"):
                    game.media.cover_path = downloaded["cover_path"]
                if downloaded.get("cover_thumb_path"):
                    game.media.cover_thumb_path = downloaded["cover_thumb_path"]
                if downloaded.get("logo_path"):
                    game.media.logo_path = downloaded["logo_path"]
                if downloaded.get("hero_bg_path"):
                    game.media.hero_bg_path = downloaded["hero_bg_path"]
                if not game.media.screenshot_dir and downloaded.get("downloaded_screenshot_dir"):
                    game.media.screenshot_dir = downloaded["downloaded_screenshot_dir"]

            imported_ids.append(game.id)
        except Exception as exc:
            errors.append({"title": item.title, "error": str(exc)})

    if imported_ids:
        setting = await db.get(AppStateSetting, "last_active_game_id")
        if setting:
            setting.value = imported_ids[-1]
        else:
            db.add(AppStateSetting(key="last_active_game_id", value=imported_ids[-1]))

    await db.commit()
    return {
        "imported_count": len(imported_ids),
        "imported_ids": imported_ids,
        "errors": errors,
    }


# ──────────────────── 3. 存档目录一键快照备份与恢复 ────────────────────


@router.get("/backups/{game_id}")
async def get_game_backups(game_id: int) -> dict[str, Any]:
    return {"game_id": game_id, "items": list_save_backups(game_id)}


@router.post("/backups/{game_id}")
async def create_game_backup(
    game_id: int,
    payload: BackupCreateRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(Game).where(Game.id == game_id).options(selectinload(Game.media))
    game = (await db.execute(stmt)).scalar_one_or_none()
    if not game or not game.media:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    try:
        return create_save_backup(
            game_id=game_id,
            save_dir=game.media.save_dir,
            note=payload.note if payload else "",
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/backups/{game_id}/{filename}")
async def remove_game_backup(game_id: int, filename: str) -> dict[str, Any]:
    try:
        deleted = delete_save_backup(game_id, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail="未找到指定的备份文件")
    return {"deleted": True, "filename": filename}


@router.post("/backups/{game_id}/{filename}/restore")
async def restore_game_backup_endpoint(
    game_id: int,
    filename: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(Game).where(Game.id == game_id).options(selectinload(Game.media))
    game = (await db.execute(stmt)).scalar_one_or_none()
    if not game or not game.media or not game.media.save_dir:
        raise HTTPException(status_code=400, detail="未找到游戏或尚未绑定存档目录")

    try:
        return restore_save_backup(game_id, game.media.save_dir, filename)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ──────────────────── 4. 游戏库聚合统计 ────────────────────


@router.get("/stats")
async def get_library_stats(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    stmt = select(Game).options(selectinload(Game.play_record))
    games = list((await db.execute(stmt)).scalars().all())

    status_counts = Counter(g.status for g in games)
    tag_counts = Counter(t for g in games for t in (g.tags or []) if t)
    total_seconds = sum(
        g.play_record.total_seconds for g in games if g.play_record
    )

    return {
        "total_games": len(games),
        "status_counts": {
            "todo": status_counts.get("todo", 0),
            "playing": status_counts.get("playing", 0),
            "done": status_counts.get("done", 0),
        },
        "total_play_seconds": total_seconds,
        "top_tags": [{"tag": k, "count": v} for k, v in tag_counts.most_common(40)],
    }


# ──────────────────── 5. 跨平台本地路径辅助浏览与校验 ────────────────────


def _list_windows_drives() -> list[dict[str, Any]]:
    drives: list[dict[str, Any]] = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:\\")
        if root.exists():
            drives.append({"name": f"{letter}:\\", "path": str(root), "is_dir": True})
    return drives


@router.post("/browse-path")
async def browse_local_path(payload: BrowsePathRequest) -> dict[str, Any]:
    """跨平台轻量级本地目录浏览（纯 Web 模式下用于选择可执行文件，不依赖 GUI 弹窗）"""
    raw = (payload.path or "").strip()
    exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in payload.extensions if e}

    if not raw:
        if sys.platform == "win32":
            return {
                "current_dir": "",
                "parent_dir": None,
                "platform": os_adapter.platform_name,
                "entries": _list_windows_drives(),
            }
        target = Path.home()
    else:
        target = Path(raw).expanduser()
        if target.is_file():
            target = target.parent

    if not target.exists() or not target.is_dir():
        target = Path.home() if Path.home().exists() else Path(os.getcwd())

    resolved = target.resolve()
    parent_dir: str | None
    if sys.platform == "win32" and resolved.parent == resolved:
        parent_dir = ""
    elif resolved.parent != resolved:
        parent_dir = str(resolved.parent)
    else:
        parent_dir = None

    dirs: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    try:
        for child in resolved.iterdir():
            name = child.name
            if name.startswith(".") and raw == "":
                continue
            try:
                is_dir = child.is_dir()
            except OSError:
                continue
            if is_dir:
                dirs.append({"name": name, "path": str(child), "is_dir": True})
            else:
                if exts and child.suffix.lower() not in exts:
                    continue
                files.append({"name": name, "path": str(child), "is_dir": False})
    except PermissionError:
        pass

    dirs.sort(key=lambda item: item["name"].lower())
    files.sort(key=lambda item: item["name"].lower())

    return {
        "current_dir": str(resolved),
        "parent_dir": parent_dir,
        "platform": os_adapter.platform_name,
        "entries": (dirs + files)[:200],
    }


@router.post("/validate-path")
async def validate_local_path(payload: ValidatePathRequest) -> dict[str, Any]:
    """校验用户输入的启动程序路径或 URI 协议"""
    raw = (payload.path or "").strip()
    if not raw:
        return {
            "valid": False,
            "exists": False,
            "is_uri": False,
            "is_file": False,
            "normalized_path": "",
            "platform": os_adapter.platform_name,
        }

    lower = raw.lower()
    is_uri = any(
        lower.startswith(prefix)
        for prefix in ("steam://", "http://", "https://", "com.epicgames.launcher://")
    )
    if is_uri:
        return {
            "valid": True,
            "exists": True,
            "is_uri": True,
            "is_file": False,
            "normalized_path": raw,
            "platform": os_adapter.platform_name,
        }

    p = Path(raw).expanduser()
    exists = p.exists()
    is_file = p.is_file()
    return {
        "valid": bool(is_file or sys.platform != "win32"),
        "exists": exists,
        "is_uri": False,
        "is_file": is_file,
        "normalized_path": str(p),
        "platform": os_adapter.platform_name,
    }
