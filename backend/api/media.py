import asyncio
import logging
import random
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.config import DATA_DIR, WALLPAPERS_DIR
from backend.core.os_adapter import os_adapter
from backend.db.database import get_db
from backend.db.models import AppStateSetting, Game
from backend.schemas import GameOut
from backend.scrapers.asset_search import search_asset_candidates
from backend.services.media_service import (
    build_media_proxy_headers,
    delete_local_media_cache,
    format_download_error_zh,
    get_or_create_thumbnail,
    is_hls_response,
    is_remote_http_url,
    normalize_steam_media_https,
    resolve_remote_video_stream,
    rewrite_hls_manifest,
    save_game_asset_bytes,
    validate_proxy_target_url,
)
from backend.services.task_manager import task_manager

logger = logging.getLogger("tsumugi.api.media")
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
    elif asset_type == "pv":
        game.media.pv_mode = "download"
    elif asset_type == "bgm":
        game.media.bgm_mode = "download"

    await db.commit()
    return {"game_id": game_id, "asset_type": asset_type, **saved}


@router.post("/drop-local-cache/{game_id}", response_model=GameOut)
async def drop_local_media_cache(
    game_id: int,
    asset_type: Literal["pv", "bgm"] = Query(..., description="目标影音类型: pv / bgm"),
    db: AsyncSession = Depends(get_db),
):
    """仅删除本地缓存视频/音频文件以释放磁盘空间，若有远程链接则保留并自动切为仅链接模式"""
    stmt = (
        select(Game)
        .where(Game.id == game_id)
        .options(selectinload(Game.media), selectinload(Game.play_record))
    )
    game = (await db.execute(stmt)).scalar_one_or_none()
    if not game or not game.media:
        raise HTTPException(status_code=404, detail="未找到游戏或其媒体信息")

    delete_local_media_cache(game_id, asset_type)

    if asset_type == "pv":
        remote = (game.media.pv_remote_url or "").strip()
        if is_remote_http_url(remote):
            game.media.pv_url_or_path = remote
            game.media.pv_mode = "link_only"
        else:
            game.media.pv_url_or_path = ""
            game.media.pv_remote_url = ""
            game.media.pv_mode = "none"
    else:
        remote = (game.media.bgm_remote_url or "").strip()
        if is_remote_http_url(remote):
            game.media.bgm_path = remote
            game.media.bgm_mode = "link_only"
        else:
            game.media.bgm_path = ""
            game.media.bgm_remote_url = ""
            game.media.bgm_mode = "none"

    await db.commit()
    refreshed = (await db.execute(stmt)).scalar_one()
    return GameOut.model_validate(refreshed)


@router.post("/cache-remote/{game_id}")
async def cache_remote_media_to_local(
    game_id: int,
    asset_type: Literal["pv", "bgm"] = Query(..., description="目标影音类型: pv / bgm"),
    db: AsyncSession = Depends(get_db),
):
    """将当前「仅保留在线链接」的 PV 或 OP 触发后台下载到本地缓存"""
    from backend.api.scraper import _background_download_pv, _background_download_selected_bgm

    stmt = (
        select(Game)
        .where(Game.id == game_id)
        .options(selectinload(Game.media), selectinload(Game.play_record))
    )
    game = (await db.execute(stmt)).scalar_one_or_none()
    if not game or not game.media:
        raise HTTPException(status_code=404, detail="未找到游戏或其媒体信息")

    proxy_row = await db.get(AppStateSetting, "proxy_url")
    proxy_url = str(proxy_row.value or "").strip() if proxy_row else ""

    if asset_type == "pv":
        remote = (game.media.pv_remote_url or "").strip()
        if not is_remote_http_url(remote) and is_remote_http_url(game.media.pv_url_or_path):
            remote = game.media.pv_url_or_path.strip()
        if not is_remote_http_url(remote):
            raise HTTPException(status_code=400, detail="当前没有可下载的在线宣传片链接")

        game.media.pv_remote_url = remote
        if not game.media.pv_url_or_path:
            game.media.pv_url_or_path = remote
        game.media.pv_mode = "download"
        await db.commit()

        task_info = task_manager.set_task(game_id, "pv", "queued", 0, "等待下载宣传片…")
        steam_appid = str((game.external_ids or {}).get("steam") or "")
        asyncio.create_task(
            _background_download_pv(
                game_id=game_id,
                url=remote,
                proxy_url=proxy_url,
                steam_appid=steam_appid,
            )
        )
    else:
        remote = (game.media.bgm_remote_url or "").strip()
        if not is_remote_http_url(remote) and is_remote_http_url(game.media.bgm_path):
            remote = game.media.bgm_path.strip()
        if not is_remote_http_url(remote):
            raise HTTPException(status_code=400, detail="当前没有可下载的在线主题曲链接")

        game.media.bgm_remote_url = remote
        if not game.media.bgm_path:
            game.media.bgm_path = remote
        game.media.bgm_mode = "download"
        await db.commit()

        task_info = task_manager.set_task(game_id, "bgm", "queued", 0, "等待下载主题曲…")
        asyncio.create_task(_background_download_selected_bgm(game_id, remote, proxy_url))

    refreshed = (await db.execute(stmt)).scalar_one()
    game_data = GameOut.model_validate(refreshed).model_dump(mode="json")
    return {**game_data, "download_task": task_info}


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


@router.get("/proxy")
async def proxy_media_resource(
    url: str = Query(..., min_length=8, description="待代理播放的远程视频直链或 HLS (.m3u8) 地址"),
    range_header: str | None = Header(None, alias="Range"),
    db: AsyncSession = Depends(get_db),
):
    """
    本地流媒体与 HLS (.m3u8) 代理接口：
    - 拦截非 http/https 协议与内网回环/私有网段地址（防 SSRF）；
    - 自动透传项目代理配置与对应站点 Referer/UA；
    - 对 HLS 清单 (.m3u8) 自动补全并重写子清单、音频轨 URI 与分片地址；
    - 对直链视频与分片以 StreamingResponse 流式转发，透传 Range / 206 实现流畅拖拽。
    """
    try:
        validated = validate_proxy_target_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    target_url = normalize_steam_media_https(validated)
    proxy_row = await db.get(AppStateSetting, "proxy_url")
    proxy_url = str(proxy_row.value or "").strip() if proxy_row else ""

    req_headers = build_media_proxy_headers(target_url, range_header=range_header)
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, read=60.0),
        proxy=proxy_url or None,
        follow_redirects=True,
    )

    try:
        req = client.build_request("GET", target_url, headers=req_headers)
        upstream_resp = await client.send(req, stream=True)
    except Exception as exc:
        await client.aclose()
        logger.warning("Media proxy upstream request failed for %s: %s", target_url, exc)
        raise HTTPException(status_code=502, detail=format_download_error_zh(exc, media_kind="video"))

    final_url = str(upstream_resp.url or target_url)
    try:
        validate_proxy_target_url(final_url)
    except ValueError as exc:
        await upstream_resp.aclose()
        await client.aclose()
        raise HTTPException(status_code=400, detail=str(exc))

    if upstream_resp.status_code >= 400:
        code = upstream_resp.status_code
        await upstream_resp.aclose()
        await client.aclose()
        out_status = code if code in (403, 404, 410, 416) else 502
        raise HTTPException(
            status_code=out_status,
            detail=format_download_error_zh(f"HTTP Error {code}", media_kind="video"),
        )

    upstream_ct = upstream_resp.headers.get("content-type") or ""
    if is_hls_response(final_url, upstream_ct) or is_hls_response(target_url, ""):
        try:
            raw_bytes = await upstream_resp.aread()
        except Exception as exc:
            logger.warning("Media proxy failed reading HLS manifest %s: %s", final_url, exc)
            raise HTTPException(
                status_code=502,
                detail=format_download_error_zh(exc, media_kind="video"),
            )
        finally:
            await upstream_resp.aclose()
            await client.aclose()

        manifest_text = raw_bytes.decode("utf-8", errors="replace")
        rewritten = rewrite_hls_manifest(manifest_text, base_url=final_url, proxy_prefix="/api/media/proxy")
        return Response(
            content=rewritten,
            status_code=200,
            media_type="application/vnd.apple.mpegurl",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache",
            },
        )

    media_type = upstream_ct.split(";")[0].strip() or "application/octet-stream"
    resp_headers: dict[str, str] = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
    }
    for hk in ("content-length", "content-range", "accept-ranges"):
        if hk in upstream_resp.headers:
            resp_headers[hk] = upstream_resp.headers[hk]

    async def _iter_proxy_chunks():
        try:
            async for chunk in upstream_resp.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await upstream_resp.aclose()
            await client.aclose()

    return StreamingResponse(
        _iter_proxy_chunks(),
        status_code=upstream_resp.status_code,
        media_type=media_type,
        headers=resp_headers,
    )


@router.get("/video-stream")
async def proxy_remote_video_stream(
    url: str = Query(..., min_length=8, description="待在线播放的远程视频页面或直链地址"),
    range_header: str | None = Header(None, alias="Range"),
    db: AsyncSession = Depends(get_db),
):
    """在线视频流播放代理（兼容 Bilibili / YouTube 网页链接与防盗链视频直链，支持 Range 拖拽）"""
    try:
        cleaned = normalize_steam_media_https(validate_proxy_target_url(url))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    proxy_row = await db.get(AppStateSetting, "proxy_url")
    proxy_url = str(proxy_row.value or "").strip() if proxy_row else ""

    try:
        stream_url, upstream_headers = await resolve_remote_video_stream(cleaned, proxy_url=proxy_url)
    except Exception as exc:
        logger.warning("Remote video stream resolve failed for %s: %s", cleaned, exc)
        raise HTTPException(status_code=400, detail=format_download_error_zh(exc, media_kind="video"))

    req_headers: dict[str, str] = {}
    for key in ("User-Agent", "Referer", "Origin"):
        if key in upstream_headers:
            req_headers[key] = upstream_headers[key]
    if range_header:
        req_headers["Range"] = range_header

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, read=60.0),
        proxy=proxy_url or None,
        follow_redirects=True,
    )
    try:
        req = client.build_request("GET", stream_url, headers=req_headers)
        upstream_resp = await client.send(req, stream=True)
        if upstream_resp.status_code >= 400:
            code = upstream_resp.status_code
            await upstream_resp.aclose()
            await client.aclose()
            raise HTTPException(
                status_code=502,
                detail=format_download_error_zh(f"HTTP Error {code}", media_kind="video"),
            )
    except HTTPException:
        raise
    except Exception as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=format_download_error_zh(exc, media_kind="video"))

    media_type = upstream_resp.headers.get("content-type") or "video/mp4"
    resp_headers: dict[str, str] = {}
    for hk in ("content-length", "content-range", "accept-ranges"):
        if hk in upstream_resp.headers:
            resp_headers[hk] = upstream_resp.headers[hk]

    async def _iter_chunks():
        try:
            async for chunk in upstream_resp.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await upstream_resp.aclose()
            await client.aclose()

    return StreamingResponse(
        _iter_chunks(),
        status_code=upstream_resp.status_code,
        media_type=media_type,
        headers=resp_headers,
    )


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
