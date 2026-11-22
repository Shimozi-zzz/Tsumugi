import random
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.config import DATA_DIR, WALLPAPERS_DIR
from backend.core.os_adapter import os_adapter
from backend.db.database import get_db
from backend.db.models import AppStateSetting, Game
from backend.scrapers.asset_search import search_asset_candidates
from backend.services.media_service import get_or_create_thumbnail, save_game_asset_bytes

router = APIRouter(prefix="/api/media", tags=["Media"])

ASSET_FIELD_MAP = {
    "cover": "cover_path",
    "logo": "logo_path",
    "hero": "hero_bg_path",
    "spine": "custom_spine_path",
    "custom_spine": "custom_spine_path",
    "pv": "pv_url_or_path",
    "bgm": "bgm_path",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
AUDIO_MEDIA_TYPES = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".webm": "audio/webm",
    ".opus": "audio/opus",
}
VIDEO_MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".m4v": "video/mp4",
}
BACKDROP_THUMB_WIDTH = 480
MAX_FILES_PER_FOLDER = 300


def _resolve_data_path(raw: str) -> Path:
    target = Path(raw).expanduser()
    if not target.is_absolute():
        target = DATA_DIR / target
    return target


def _display_path(file_path: Path) -> str:
    """优先返回 data/ 相对路径（便于缩略图缓存与可移植），否则返回绝对路径"""
    try:
        return file_path.resolve().relative_to(DATA_DIR.resolve()).as_posix()
    except ValueError:
        return str(file_path)


def _screenshot_folder_for(game: Game) -> Path:
    raw_dir = (game.media.screenshot_dir or "").strip() if game.media else ""
    if raw_dir:
        return _resolve_data_path(raw_dir)
    return DATA_DIR / "assets" / str(game.id) / "screenshots"


def _collect_images(folder: Path, limit: int = MAX_FILES_PER_FOLDER) -> list[Path]:
    if not folder.exists() or not folder.is_dir():
        return []
    found: list[Path] = []
    try:
        for f in folder.iterdir():
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                found.append(f)
                if len(found) >= limit:
                    break
    except OSError:
        return []
    return found


@router.get("/search-pv")
async def search_pv_by_platform(
    q: str = Query("", description="游戏名称或原名"),
    source: str = Query("auto", description="PV 平台: auto / steam / bilibili / youtube"),
    steam_appid: str = Query("", description="可选：已知 Steam AppID"),
    alt_title: str = Query("", description="可选：游戏原名/别名"),
    db: AsyncSession = Depends(get_db),
):
    """宣传片 PV 多平台分选检索入口（默认 auto 优先 Steam 官方预告片）"""
    proxy_row = await db.get(AppStateSetting, "proxy_url")
    proxy_url = str(proxy_row.value or "").strip() if proxy_row else ""
    return await search_asset_candidates(
        asset_type="pv",
        query=q,
        source=source,
        proxy_url=proxy_url,
        steam_appid=steam_appid,
        alt_title=alt_title,
    )


@router.post("/upload/{game_id}")
async def upload_game_asset(
    game_id: int,
    asset_type: str = Query(..., description="上传的资源类型: cover/logo/hero/custom_spine/pv"),
    file: UploadFile = File(..., description="上传的资源文件"),
    db: AsyncSession = Depends(get_db),
):
    """上传游戏的自定义视觉资产"""
    if asset_type not in ASSET_FIELD_MAP:
        raise HTTPException(status_code=400, detail=f"未知的资源类型: {asset_type}")

    stmt = select(Game).where(Game.id == game_id).options(selectinload(Game.media))
    game = (await db.execute(stmt)).scalar_one_or_none()
    if not game or not game.media:
        raise HTTPException(status_code=404, detail="未找到游戏或其媒体信息")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传的文件为空")

    default_names = {"pv": "asset.mp4", "bgm": "asset.mp3"}
    filename = file.filename or default_names.get(asset_type, "asset.png")
    if asset_type == "bgm" and Path(filename).suffix.lower() not in AUDIO_MEDIA_TYPES:
        raise HTTPException(
            status_code=400,
            detail="原声音频仅支持 .mp3 / .flac / .ogg / .wav / .m4a 格式",
        )

    try:
        saved = save_game_asset_bytes(
            game_id=game_id,
            asset_type=asset_type,
            filename=filename,
            content=content,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"文件解析或保存失败: {exc}")

    target_field = ASSET_FIELD_MAP[asset_type]
    setattr(game.media, target_field, saved["path"])
    if asset_type == "cover":
        game.media.cover_thumb_path = saved.get("thumb_path", "")

    await db.commit()
    return {"game_id": game_id, "asset_type": asset_type, **saved}


@router.get("/thumb")
@router.get("/thumbnail")
async def stream_thumbnail(
    path: str = Query(..., description="data/ 下的相对路径或本地截图绝对路径"),
    width: int = Query(360, ge=80, le=1200),
):
    """按需生成并返回 WebP 缩略图（同时兼容 /thumb 与 /thumbnail）"""
    try:
        thumb_path = get_or_create_thumbnail(path, width=width)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"缩略图生成失败: {exc}")
    return FileResponse(thumb_path, media_type="image/webp")


@router.get("/raw")
async def stream_raw_image(path: str = Query(..., description="本地图片路径")):
    """直接流式返回本地原图文件（供灯箱查看）"""
    target = Path(path)
    if not target.is_absolute():
        target = DATA_DIR / target

    if not target.exists() or not target.is_file() or target.suffix.lower() not in IMAGE_EXTS:
        raise HTTPException(status_code=404, detail="找不到有效的图片文件")
    return FileResponse(target)


@router.get("/audio")
async def stream_audio(path: str = Query(..., description="data/ 下的相对路径或本地音频绝对路径")):
    """流式返回原声音频（FileResponse 原生支持 HTTP Range，可拖动进度）"""
    target = _resolve_data_path(path)
    media_type = AUDIO_MEDIA_TYPES.get(target.suffix.lower())
    if not media_type or not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="找不到有效的音频文件")
    return FileResponse(target, media_type=media_type)


@router.get("/video")
async def stream_video(path: str = Query(..., description="data/ 下的相对路径或合法本地视频路径")):
    """本地宣传片 PV 流播接口（带路径安全校验，原生支持 HTTP Range 拖拽秒播）"""
    raw = (path or "").strip()
    if not raw or "\x00" in raw:
        raise HTTPException(status_code=400, detail="无效的视频路径")

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        data_root = DATA_DIR.resolve()
        resolved = (data_root / candidate).resolve()
        if not resolved.is_relative_to(data_root):
            raise HTTPException(status_code=403, detail="禁止越权访问数据目录外的文件")
    else:
        resolved = candidate.resolve()

    media_type = VIDEO_MEDIA_TYPES.get(resolved.suffix.lower())
    if not media_type or not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="找不到有效的本地视频文件")
    return FileResponse(resolved, media_type=media_type)


@router.get("/random-backdrop")
async def random_backdrop(
    exclude_nsfw: bool = Query(True, description="是否排除 NSFW 游戏的图源"),
    db: AsyncSession = Depends(get_db),
):
    """
    回廊「记忆漫游」随机背景：
    图池 = data/wallpapers/ 本地壁纸 + 全库游戏截图目录；图池为空时兜底采用 Hero / 封面。
    返回 480px WebP 缩略图地址以保证重度模糊渲染的性能。
    """
    candidates: list[dict] = []

    for f in _collect_images(WALLPAPERS_DIR):
        candidates.append({"path": _display_path(f), "source": "wallpaper", "game_id": None})

    stmt = select(Game).options(selectinload(Game.media))
    games = list((await db.execute(stmt)).scalars().all())
    eligible = [g for g in games if not (exclude_nsfw and g.is_nsfw)]

    for g in eligible:
        for f in _collect_images(_screenshot_folder_for(g)):
            candidates.append({"path": _display_path(f), "source": "screenshot", "game_id": g.id})

    if not candidates:
        for g in eligible:
            if not g.media:
                continue
            for field in ("hero_bg_path", "cover_path"):
                raw = (getattr(g.media, field) or "").strip()
                if raw and _resolve_data_path(raw).is_file():
                    candidates.append({"path": raw, "source": field, "game_id": g.id})
                    break

    if not candidates:
        return {}

    pick = random.choice(candidates)
    pick["thumb_url"] = (
        f"/api/media/thumb?path={quote(pick['path'], safe='')}&width={BACKDROP_THUMB_WIDTH}"
    )
    pick["pool_size"] = len(candidates)
    return pick


@router.get("/screenshots/{game_id}")
async def list_game_screenshots(game_id: int, db: AsyncSession = Depends(get_db)):
    """扫描游戏绑定的本地截图目录（或下载的默认截图目录），按修改时间倒序返回列表"""
    stmt = select(Game).where(Game.id == game_id).options(selectinload(Game.media))
    game = (await db.execute(stmt)).scalar_one_or_none()
    if not game or not game.media:
        return {"game_id": game_id, "items": []}

    raw_dir = (game.media.screenshot_dir or "").strip()
    if raw_dir:
        folder = Path(raw_dir)
        if not folder.is_absolute():
            folder = DATA_DIR / folder
    else:
        # 若未手动绑定本地截图目录，自动回退检查刮削下载的 CG/截图目录
        folder = DATA_DIR / "assets" / str(game_id) / "screenshots"

    if not folder.exists() or not folder.is_dir():
        return {"game_id": game_id, "items": []}

    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    items = []
    for f in files[:120]:
        try:
            display_path = f.relative_to(DATA_DIR).as_posix()
        except ValueError:
            display_path = str(f)
        items.append({"name": f.name, "path": display_path, "mtime": f.stat().st_mtime})

    return {"game_id": game_id, "items": items}


@router.post("/open-folder/{game_id}")
async def open_bound_folder(
    game_id: int,
    target: str = Query(..., description="save / screenshot / game"),
    db: AsyncSession = Depends(get_db),
):
    """唤起系统文件管理器打开绑定的存档、截图或游戏安装目录"""
    stmt = select(Game).where(Game.id == game_id).options(selectinload(Game.media))
    game = (await db.execute(stmt)).scalar_one_or_none()
    if not game or not game.media:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    if target == "save":
        folder_path = game.media.save_dir
    elif target == "screenshot":
        folder_path = game.media.screenshot_dir
        if not folder_path:
            default_ss = DATA_DIR / "assets" / str(game_id) / "screenshots"
            if default_ss.exists():
                folder_path = str(default_ss)
    elif target == "game":
        folder_path = str(Path(game.media.exe_path).parent) if game.media.exe_path else ""
    else:
        raise HTTPException(status_code=400, detail=f"不支持的目录类型: {target}")

    if not folder_path:
        raise HTTPException(status_code=400, detail="尚未绑定该目录路径")

    resolved = Path(folder_path)
    if not resolved.is_absolute():
        resolved = DATA_DIR / resolved

    ok = os_adapter.open_local_folder(str(resolved))
    return {"opened": ok, "path": str(resolved), "adapter": os_adapter.platform_name}
