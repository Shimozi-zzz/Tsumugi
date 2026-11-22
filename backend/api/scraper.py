import asyncio
import logging
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.api.settings import DEFAULT_SETTINGS, resolve_bangumi_token
from backend.db.database import AsyncSessionLocal, get_db
from backend.db.models import AppStateSetting, Game, GameMediaPath, PlayRecord
from backend.schemas import (
    AggregateRequest,
    AssetApplyRequest,
    GameOut,
    MusicDownloadRequest,
    ScraperImportRequest,
)
from backend.scrapers.aggregator import MetadataAggregator
from backend.scrapers.asset_search import (
    download_pv_to_local,
    search_asset_candidates,
)
from backend.scrapers.bangumi import BANGUMI_USER_AGENT, BGM_BASE_URL
from backend.scrapers.base import clean_scraped_tags, normalize_platform_badge
from backend.scrapers.music import (
    download_op_music,
    resolve_preview_stream,
    search_op_music,
)
from backend.services.asset_downloader import (
    _build_asset_headers,
    download_game_assets,
    download_single_image_asset,
)
from backend.services.media_service import generate_pinyin_initials
from backend.services.task_manager import task_manager

logger = logging.getLogger("tsumugi.api.scraper")
router = APIRouter(prefix="/api/scraper", tags=["Scraper"])


def _extract_bangumi_id(
    explicit_id: str = "",
    external_ids: dict[str, Any] | None = None,
) -> str:
    val = (explicit_id or "").strip()
    if val:
        return val
    ids = external_ids or {}
    for key in ("bgm", "bangumi", "bangumi_id"):
        raw = str(ids.get(key) or "").strip()
        if raw:
            return raw
    return ""


async def _background_download_pv(
    game_id: int,
    url: str,
    proxy_url: str,
    mime_hint: str = "",
) -> None:
    """后台异步强制下载宣传片至 data/assets/{game_id}/pv.mp4，并更新数据库路径"""
    try:
        rel_path = await download_pv_to_local(
            game_id=game_id,
            url=url,
            proxy_url=proxy_url,
            mime_hint=mime_hint,
        )
        async with AsyncSessionLocal() as db:
            stmt = select(Game).where(Game.id == game_id).options(selectinload(Game.media))
            game = (await db.execute(stmt)).scalar_one_or_none()
            if game and game.media:
                game.media.pv_url_or_path = rel_path
                await db.commit()
    except Exception as exc:
        logger.debug("Background PV download failed for game_id=%s: %s", game_id, exc)


async def _background_download_selected_bgm(
    game_id: int,
    bgm_url: str,
    proxy_url: str,
) -> None:
    """后台异步下载用户选中的主题曲原声至 data/assets/{game_id}/bgm.{ext}"""
    task_manager.set_task(game_id, "bgm", "downloading", 10, "正在下载主题曲…")
    try:
        rel_path = await download_op_music(
            game_id=game_id,
            source_url=bgm_url,
            preview_url=bgm_url if bgm_url.lower().endswith((".m4a", ".mp3", ".ogg", ".wav")) else "",
            proxy_url=proxy_url,
        )
        async with AsyncSessionLocal() as db:
            stmt = select(Game).where(Game.id == game_id).options(selectinload(Game.media))
            game = (await db.execute(stmt)).scalar_one_or_none()
            if game and game.media:
                game.media.bgm_path = rel_path
                await db.commit()
        task_manager.mark_done(game_id, "bgm", "主题曲已缓存到本地")
    except Exception as exc:
        task_manager.mark_error(game_id, "bgm", f"主题曲下载失败: {exc}")
        logger.debug("Background selected BGM download failed for game_id=%s: %s", game_id, exc)


async def _background_auto_fetch_bgm(game_id: int, query: str, proxy_url: str) -> None:
    """后台静默尝试匹配并下载一首最相关 OP 原声，任何异常均静默跳过不阻塞入库"""
    task_manager.set_task(game_id, "bgm", "downloading", 10, "正在匹配主题曲…")
    try:
        candidates = await search_op_music(query, proxy_url=proxy_url)
        if not candidates:
            task_manager.mark_error(game_id, "bgm", "未匹配到可用主题曲")
            return
        best = candidates[0]
        task_manager.update_progress(game_id, "bgm", 45, "正在下载主题曲…")
        rel_path = await download_op_music(
            game_id=game_id,
            source_url=str(best.get("source_url") or ""),
            preview_url=str(best.get("preview_url") or ""),
            proxy_url=proxy_url,
        )
        async with AsyncSessionLocal() as db:
            stmt = select(Game).where(Game.id == game_id).options(selectinload(Game.media))
            game = (await db.execute(stmt)).scalar_one_or_none()
            if game and game.media and not game.media.bgm_path:
                game.media.bgm_path = rel_path
                await db.commit()
        task_manager.mark_done(game_id, "bgm", "主题曲已缓存到本地")
    except Exception as exc:
        task_manager.mark_error(game_id, "bgm", f"主题曲下载失败: {exc}")
        logger.debug("Background auto_fetch_bgm skipped for game_id=%s: %s", game_id, exc)


async def _load_aggregator(db: AsyncSession) -> tuple[MetadataAggregator, dict[str, Any]]:
    result = await db.execute(select(AppStateSetting))
    stored = {row.key: row.value for row in result.scalars().all()}
    cfg = {**DEFAULT_SETTINGS, **stored}

    proxy_url = str(cfg.get("proxy_url") or "")
    api_keys = dict(cfg.get("api_keys")) if isinstance(cfg.get("api_keys"), dict) else {}
    bgm_tok = resolve_bangumi_token(cfg)
    if bgm_tok and not api_keys.get("bangumi"):
        api_keys["bangumi"] = bgm_tok
    allow_nsfw = bool(cfg.get("allow_nsfw_scrape", True))

    aggregator = MetadataAggregator(
        proxy_url=proxy_url,
        api_keys=api_keys,
        allow_nsfw=allow_nsfw,
    )
    return aggregator, cfg


async def _set_last_active(db: AsyncSession, game_id: int) -> None:
    setting = await db.get(AppStateSetting, "last_active_game_id")
    if setting:
        setting.value = game_id
    else:
        db.add(AppStateSetting(key="last_active_game_id", value=game_id))


@router.get("/search")
async def search_metadata(
    q: str = Query(..., min_length=1, description="游戏搜索关键词"),
    source: str = Query(
        "aggregated",
        description="刮削源: aggregated / bgm / vndb / steam / sgdb / tgal",
    ),
    limit: int = Query(8, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    """多源或单源检索候选游戏列表"""
    aggregator, cfg = await _load_aggregator(db)
    src = source.strip().lower()

    if src == "aggregated":
        items = await aggregator.search_aggregated(q, limit=limit)
    else:
        if not aggregator.get_scraper(src):
            raise HTTPException(status_code=400, detail=f"不支持的刮削源: {source}")
        items = await aggregator.search_source(src, q, limit=limit)

    return {
        "source": src,
        "query": q,
        "count": len(items),
        "sgdb_configured": bool((cfg.get("api_keys") or {}).get("steamgriddb")),
        "items": [it.model_dump() for it in items],
    }


@router.get("/detail/{source}/{external_id}")
async def get_source_detail(
    source: str,
    external_id: str,
    db: AsyncSession = Depends(get_db),
):
    """拉取单个平台的完整详情与视觉资产链接"""
    aggregator, _ = await _load_aggregator(db)
    if not aggregator.get_scraper(source):
        raise HTTPException(status_code=400, detail=f"不支持的刮削源: {source}")

    item = await aggregator.get_detail(source, external_id)
    if not item:
        raise HTTPException(status_code=404, detail="未从该平台获取到有效详情")
    return item.model_dump()


@router.post("/aggregate")
async def aggregate_preview(
    payload: AggregateRequest,
    db: AsyncSession = Depends(get_db),
):
    """并发调用所有可用源并按最优权重拼装元数据与高清视觉资产，供入库前预览微调"""
    aggregator, _ = await _load_aggregator(db)
    res = await aggregator.aggregate_detail(
        keyword=payload.keyword,
        external_ids=payload.external_ids,
    )
    return {
        "item": res["item"].model_dump(),
        "matched_sources": res["matched_sources"],
        "sources_detail": res["sources_detail"],
    }


@router.post("/import", response_model=GameOut)
async def import_scraped_game(
    payload: ScraperImportRequest,
    db: AsyncSession = Depends(get_db),
):
    """确认刮削结果入库，视觉图片自动 WebP 落盘，PV/BGM 丢入后台异步本地化下载不阻塞响应"""
    _, cfg = await _load_aggregator(db)
    proxy_url = str(cfg.get("proxy_url") or "")

    resolved_bgm_id = _extract_bangumi_id(payload.bangumi_id, payload.external_ids)

    game = Game(
        title=payload.title.strip(),
        sub_title=payload.sub_title.strip(),
        pinyin_initials=generate_pinyin_initials(payload.title.strip()),
        developer=payload.developer.strip(),
        publisher=payload.publisher.strip(),
        release_date=payload.release_date.strip(),
        synopsis=payload.synopsis.strip(),
        tags=[t.strip() for t in payload.tags if t and t.strip()],
        status=payload.status,
        edition=payload.edition or "collector",
        is_nsfw=payload.is_nsfw,
        source_platform=normalize_platform_badge(payload.source_platform, payload.external_ids),
        bangumi_id=resolved_bgm_id,
        external_ids=payload.external_ids,
        locked_fields=[],
    )

    selected_pv = (payload.selected_pv_url or "").strip()
    raw_pv = (payload.pv_url or "").strip()
    pv_download_url = selected_pv or (raw_pv if raw_pv.startswith(("http://", "https://")) else "")
    initial_pv_path = "" if pv_download_url else raw_pv

    game.media = GameMediaPath(
        exe_path=payload.exe_path.strip(),
        launch_mode=payload.launch_mode or "direct",
        launch_args=payload.launch_args.strip(),
        save_dir=payload.save_dir.strip(),
        screenshot_dir=payload.screenshot_dir.strip(),
        pv_url_or_path=initial_pv_path,
    )
    game.play_record = PlayRecord(total_seconds=0)

    db.add(game)
    await db.flush()

    # 并发下载视觉图片资产并自动转为 WebP 及生成 420px 封面缩略图（PV 交由后台异步本地化下载）
    downloaded = await download_game_assets(
        game_id=game.id,
        cover_url=payload.cover_url,
        logo_url=payload.logo_url,
        hero_bg_url=payload.hero_bg_url,
        pv_url="",
        screenshots=payload.screenshots,
        proxy_url=proxy_url,
        download_screenshots=payload.download_screenshots and not payload.screenshot_dir.strip(),
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

    await _set_last_active(db, game.id)
    await db.commit()

    # 后台异步下载宣传片 PV（绝不阻塞导入接口响应）
    if pv_download_url:
        task_manager.set_task(game.id, "pv", "queued", 0, "等待下载宣传片…")
        asyncio.create_task(
            _background_download_pv(
                game_id=game.id,
                url=pv_download_url,
                proxy_url=proxy_url,
                mime_hint=(payload.selected_pv_mime_hint or "").strip(),
            )
        )

    # 后台异步下载用户选定主题曲，或按原逻辑自动匹配 OP
    selected_bgm = (payload.selected_bgm_url or "").strip()
    if selected_bgm:
        task_manager.set_task(game.id, "bgm", "queued", 0, "等待下载主题曲…")
        asyncio.create_task(
            _background_download_selected_bgm(game.id, selected_bgm, proxy_url)
        )
    elif payload.auto_fetch_bgm:
        bgm_query = (payload.sub_title or payload.title).strip()
        if bgm_query:
            task_manager.set_task(game.id, "bgm", "queued", 0, "等待匹配主题曲…")
            asyncio.create_task(_background_auto_fetch_bgm(game.id, bgm_query, proxy_url))

    stmt = (
        select(Game)
        .where(Game.id == game.id)
        .options(selectinload(Game.media), selectinload(Game.play_record))
    )
    return (await db.execute(stmt)).scalar_one()


@router.post("/refresh/{game_id}", response_model=GameOut)
async def refresh_game_metadata(
    game_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    重新刮削已有游戏的元数据与视觉资产。
    严格遵守 game.locked_fields：被用户锁定的任何字段与资产都不会被覆盖。
    """
    stmt = (
        select(Game)
        .where(Game.id == game_id)
        .options(selectinload(Game.media), selectinload(Game.play_record))
    )
    game = (await db.execute(stmt)).scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    aggregator, cfg = await _load_aggregator(db)
    proxy_url = str(cfg.get("proxy_url") or "")
    locked = set(game.locked_fields or [])

    ext_ids = {
        str(k): str(v)
        for k, v in (game.external_ids or {}).items()
        if v
    }
    res = await aggregator.aggregate_detail(keyword=game.title, external_ids=ext_ids)
    item = res["item"]

    if not res["matched_sources"]:
        raise HTTPException(status_code=404, detail="未能从在线数据源匹配到可更新的元数据")

    text_field_map = {
        "title": item.title,
        "sub_title": item.sub_title,
        "developer": item.developer,
        "publisher": item.publisher,
        "release_date": item.release_date,
        "synopsis": item.synopsis,
    }
    for field_name, new_val in text_field_map.items():
        if field_name not in locked and new_val:
            setattr(game, field_name, new_val)
            if field_name == "title":
                game.pinyin_initials = generate_pinyin_initials(new_val)

    if "tags" not in locked and item.tags:
        game.tags = item.tags
    if "is_nsfw" not in locked:
        game.is_nsfw = item.is_nsfw

    # 合并新发现的外站 ID，并补齐 bangumi_id
    merged_ids = dict(game.external_ids or {})
    merged_ids.update(item.extra_ids)
    game.external_ids = merged_ids
    if "bangumi_id" not in locked and not game.bangumi_id:
        found_bgm_id = _extract_bangumi_id(item.bangumi_id, merged_ids)
        if found_bgm_id:
            game.bangumi_id = found_bgm_id

    if not game.media:
        game.media = GameMediaPath(game_id=game.id)

    skip_assets: set[str] = set()
    for asset_key in ("cover", "logo", "hero", "pv", "screenshots"):
        if asset_key in locked or f"{asset_key}_path" in locked:
            skip_assets.add(asset_key)

    downloaded = await download_game_assets(
        game_id=game.id,
        cover_url=item.cover_url,
        logo_url=item.logo_url,
        hero_bg_url=item.hero_bg_url,
        pv_url=item.pv_url,
        screenshots=item.screenshots,
        proxy_url=proxy_url,
        skip_types=skip_assets,
        download_screenshots=not bool(game.media.screenshot_dir),
    )

    if "cover" not in skip_assets and downloaded.get("cover_path"):
        game.media.cover_path = downloaded["cover_path"]
        game.media.cover_thumb_path = downloaded.get("cover_thumb_path", "")
    if "logo" not in skip_assets and downloaded.get("logo_path"):
        game.media.logo_path = downloaded["logo_path"]
    if "hero" not in skip_assets and downloaded.get("hero_bg_path"):
        game.media.hero_bg_path = downloaded["hero_bg_path"]
    if "pv" not in skip_assets and downloaded.get("pv_url_or_path"):
        game.media.pv_url_or_path = downloaded["pv_url_or_path"]
    if not game.media.screenshot_dir and downloaded.get("downloaded_screenshot_dir"):
        game.media.screenshot_dir = downloaded["downloaded_screenshot_dir"]

    await db.commit()
    refreshed = (await db.execute(stmt)).scalar_one()
    return refreshed


# ──────────────────── OP / 主题曲原声在线搜寻与下载 ────────────────────


@router.get("/music/search")
async def search_music_candidates(
    q: str = Query(..., min_length=1, description="游戏原名或中文名"),
    db: AsyncSession = Depends(get_db),
):
    """并发搜寻 Bilibili / YouTube 全曲 OP 与 iTunes JP 试听候选项"""
    _, cfg = await _load_aggregator(db)
    proxy_url = str(cfg.get("proxy_url") or "")
    items = await search_op_music(q, proxy_url=proxy_url)
    return {"query": q, "count": len(items), "items": items}


@router.post("/music/download/{game_id}")
async def download_music_for_game(
    game_id: int,
    payload: MusicDownloadRequest,
    db: AsyncSession = Depends(get_db),
):
    """下载选中的 OP 原声至 data/assets/{game_id}/bgm.{ext} 并绑定到该游戏"""
    stmt = select(Game).where(Game.id == game_id).options(selectinload(Game.media))
    game = (await db.execute(stmt)).scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    if not payload.source_url.strip() and not payload.preview_url.strip():
        raise HTTPException(status_code=400, detail="请提供有效的音频来源链接")

    _, cfg = await _load_aggregator(db)
    proxy_url = str(cfg.get("proxy_url") or "")

    try:
        rel_path = await download_op_music(
            game_id=game_id,
            source_url=payload.source_url,
            preview_url=payload.preview_url,
            proxy_url=proxy_url,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not game.media:
        game.media = GameMediaPath(game_id=game.id)
    game.media.bgm_path = rel_path
    await db.commit()
    return {"game_id": game_id, "bgm_path": rel_path}


@router.get("/music/preview")
async def proxy_music_preview(
    url: str = Query(..., min_length=4, description="待试听的候选音频网页或直链"),
    db: AsyncSession = Depends(get_db),
):
    """轻量音频预览代理（兼容 Bilibili/YouTube 防盗链与跨域试听）"""
    _, cfg = await _load_aggregator(db)
    proxy_url = str(cfg.get("proxy_url") or "")
    try:
        stream_url, upstream_headers = await resolve_preview_stream(url, proxy_url=proxy_url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无法解析试听流: {exc}")

    req_headers: dict[str, str] = {}
    for key in ("User-Agent", "Referer", "Origin"):
        if key in upstream_headers:
            req_headers[key] = upstream_headers[key]

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, read=60.0),
        proxy=proxy_url or None,
        follow_redirects=True,
    )
    try:
        req = client.build_request("GET", stream_url, headers=req_headers)
        upstream_resp = await client.send(req, stream=True)
        if upstream_resp.status_code >= 400:
            await upstream_resp.aclose()
            await client.aclose()
            raise HTTPException(status_code=502, detail="上游音频流暂不可访问")
    except HTTPException:
        raise
    except Exception as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"音频流代理失败: {exc}")

    media_type = upstream_resp.headers.get("content-type") or "audio/mp4"

    async def _iter_chunks():
        try:
            async for chunk in upstream_resp.aiter_bytes(chunk_size=32768):
                yield chunk
        finally:
            await upstream_resp.aclose()
            await client.aclose()

    return StreamingResponse(_iter_chunks(), media_type=media_type)


# ──────────────────── 单项视觉资产与宣传片 PV 按源在线查找与定向替换 ────────────────────


@router.get("/assets/search")
async def search_single_asset_candidates(
    asset_type: Literal["cover", "logo", "hero", "spine", "pv"] = Query(
        ..., description="目标资产槽位: cover / logo / hero / spine / pv"
    ),
    q: str = Query(..., min_length=1, description="检索关键词"),
    source: str = Query(
        "all",
        description="数据源: all / steamgriddb / vndb / bangumi / steam / touchgal / video",
    ),
    db: AsyncSession = Depends(get_db),
):
    """按资产类型与数据源并发检索多候选视觉资产或宣传片 PV"""
    _, cfg = await _load_aggregator(db)
    proxy_url = str(cfg.get("proxy_url") or "")
    api_keys = cfg.get("api_keys") if isinstance(cfg.get("api_keys"), dict) else {}
    allow_nsfw = bool(cfg.get("allow_nsfw_scrape", True))

    return await search_asset_candidates(
        asset_type=asset_type,
        query=q,
        source=source,
        proxy_url=proxy_url,
        api_keys=api_keys,
        allow_nsfw=allow_nsfw,
    )


@router.get("/assets/proxy")
async def proxy_asset_thumbnail(
    url: str = Query(..., min_length=8, description="远程候选图片地址（http/https）"),
    db: AsyncSession = Depends(get_db),
):
    """轻量级图片预览中转代理（走全局代理并附带防盗链 Referer，仅放行 image/* 响应）"""
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        raise HTTPException(status_code=400, detail="仅支持 http/https 图片链接")
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        raise HTTPException(status_code=400, detail="不允许代理本地回环地址")

    _, cfg = await _load_aggregator(db)
    proxy_url = str(cfg.get("proxy_url") or "")

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(12.0, read=25.0),
        proxy=proxy_url or None,
        follow_redirects=True,
    )
    try:
        req = client.build_request("GET", cleaned, headers=_build_asset_headers(cleaned))
        upstream_resp = await client.send(req, stream=True)
        if upstream_resp.status_code >= 400:
            await upstream_resp.aclose()
            await client.aclose()
            raise HTTPException(status_code=502, detail=f"上游图片暂不可访问 ({upstream_resp.status_code})")

        content_type = (upstream_resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            await upstream_resp.aclose()
            await client.aclose()
            raise HTTPException(status_code=400, detail=f"上游响应并非图片类型 ({content_type or 'unknown'})")
    except HTTPException:
        raise
    except Exception as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"图片代理请求失败: {exc}")

    async def _iter_chunks():
        try:
            async for chunk in upstream_resp.aiter_bytes(chunk_size=32768):
                yield chunk
        finally:
            await upstream_resp.aclose()
            await client.aclose()

    return StreamingResponse(
        _iter_chunks(),
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.post("/assets/apply/{game_id}")
async def apply_single_asset_for_game(
    game_id: int,
    payload: AssetApplyRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    定向替换指定游戏的单项视觉资产或宣传片 PV，不影响其余任何字段：
    - 图片类：下载并自动压缩为 WebP 落盘（cover 同步更新 420px 缩略图），返回 GameOut
    - PV 类：统一强制本地化下载至 data/assets/{game_id}/pv.mp4；
      async_mode=True 时立即返回兼容 GameOut 的对象及 download_task 供轮询，
      async_mode=False 时同步等待下载完成后返回最新 GameOut
    """
    stmt = (
        select(Game)
        .where(Game.id == game_id)
        .options(selectinload(Game.media), selectinload(Game.play_record))
    )
    game = (await db.execute(stmt)).scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    if not game.media:
        game.media = GameMediaPath(game_id=game.id)

    _, cfg = await _load_aggregator(db)
    proxy_url = str(cfg.get("proxy_url") or "")
    target_url = payload.url.strip()

    if payload.asset_type == "pv":
        if payload.async_mode:
            task_info = task_manager.set_task(game_id, "pv", "queued", 0, "等待下载宣传片…")
            asyncio.create_task(
                _background_download_pv(
                    game_id=game_id,
                    url=target_url,
                    proxy_url=proxy_url,
                    mime_hint=payload.mime_hint,
                )
            )
            game_data = GameOut.model_validate(game).model_dump(mode="json")
            return {**game_data, "download_task": task_info}

        try:
            rel_path = await download_pv_to_local(
                game_id=game_id,
                url=target_url,
                proxy_url=proxy_url,
                mime_hint=payload.mime_hint,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"宣传片下载失败: {exc}")
        game.media.pv_url_or_path = rel_path
    else:
        try:
            saved = await download_single_image_asset(
                game_id=game_id,
                asset_type=payload.asset_type,
                url=target_url,
                proxy_url=proxy_url,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"视觉资产下载或保存失败: {exc}")

        if payload.asset_type == "cover":
            game.media.cover_path = saved["path"]
            game.media.cover_thumb_path = saved.get("thumb_path", "")
        elif payload.asset_type == "logo":
            game.media.logo_path = saved["path"]
        elif payload.asset_type == "hero":
            game.media.hero_bg_path = saved["path"]
        elif payload.asset_type == "spine":
            game.media.custom_spine_path = saved["path"]

    await db.commit()
    refreshed = (await db.execute(stmt)).scalar_one()
    return GameOut.model_validate(refreshed)


# ──────────────────── Bangumi Token 连通性验证 ────────────────────


@router.get("/bangumi/me")
async def verify_bangumi_token(
    token: str | None = Query(None, description="可选：保存前临时验证的 Bangumi Access Token"),
    x_bangumi_token: str | None = Header(None, alias="X-Bangumi-Token"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """验证 Bangumi Access Token 有效性并返回当前账号基础信息"""
    _, cfg = await _load_aggregator(db)
    proxy_url = str(cfg.get("proxy_url") or "")

    resolved_token = (
        (token or "").strip()
        or (x_bangumi_token or "").strip()
        or resolve_bangumi_token(cfg)
    )
    if not resolved_token:
        return {"valid": False, "detail": "尚未配置 Bangumi Access Token"}

    headers = {
        "User-Agent": BANGUMI_USER_AGENT,
        "Authorization": f"Bearer {resolved_token}",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(12.0),
            follow_redirects=True,
            proxy=proxy_url or None,
        ) as client:
            resp = await client.get(f"{BGM_BASE_URL}/v0/me")
    except Exception as exc:
        return {"valid": False, "detail": f"无法连接 Bangumi 接口: {exc}"}

    if resp.status_code in (401, 403):
        return {"valid": False, "detail": "Access Token 无效或已过期"}
    if resp.status_code != 200:
        return {"valid": False, "detail": f"Bangumi 接口返回异常 ({resp.status_code})"}

    data = resp.json() if resp.content else {}
    avatar_raw = data.get("avatar")
    if isinstance(avatar_raw, dict):
        avatar = str(
            avatar_raw.get("large")
            or avatar_raw.get("medium")
            or avatar_raw.get("small")
            or ""
        )
    else:
        avatar = str(avatar_raw or "")

    return {
        "valid": True,
        "username": str(data.get("username") or ""),
        "nickname": str(data.get("nickname") or ""),
        "avatar": avatar,
    }


# ──────────────────── 单源元数据候选检索与详情预览（不下载图片、不写库） ────────────────────


@router.get("/metadata/search")
async def search_single_source_metadata(
    q: str = Query(..., min_length=1, description="检索关键词"),
    source: Literal["bangumi", "vndb", "touchgal", "steam"] = Query(
        ..., description="单一数据源: bangumi / vndb / touchgal / steam"
    ),
    limit: int = Query(10, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """按单一数据源检索轻量候选列表（供编辑页精准挑选字段替换，不触发任何图片下载）"""
    aggregator, _ = await _load_aggregator(db)
    raw_items = await aggregator.search_source(source, q, limit=limit)

    candidates: list[dict[str, Any]] = []
    for it in raw_items:
        preview = " ".join((it.synopsis or "").split())
        if len(preview) > 140:
            preview = f"{preview[:138]}…"
        candidates.append(
            {
                "external_id": it.external_id,
                "source": source,
                "title": it.title,
                "sub_title": it.sub_title,
                "developer": it.developer,
                "release_date": it.release_date,
                "cover_url": it.cover_url,
                "description_preview": preview,
            }
        )

    return {
        "source": source,
        "query": q.strip(),
        "count": len(candidates),
        "items": candidates,
    }


@router.get("/metadata/detail")
async def get_single_source_metadata_detail(
    source: Literal["bangumi", "vndb", "touchgal", "steam"] = Query(
        ..., description="单一数据源: bangumi / vndb / touchgal / steam"
    ),
    external_id: str = Query(..., min_length=1, description="该数据源的条目唯一 ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """精准拉取单一数据源条目的完整标准化元数据（经过标签清洗，严禁下载图片或写库）"""
    aggregator, _ = await _load_aggregator(db)
    item = await aggregator.get_detail(source, external_id)
    if not item:
        raise HTTPException(status_code=404, detail="未从该数据源获取到有效条目详情")

    cleaned_tags = clean_scraped_tags(
        item.tags,
        title=item.title,
        sub_title=item.sub_title,
        developer=item.developer,
        publisher=item.publisher,
    )
    resolved_bgm_id = (
        str(item.external_id or external_id).strip()
        if source == "bangumi"
        else str(item.bangumi_id or "").strip()
    )

    return {
        "source": source,
        "external_id": str(item.external_id or external_id).strip(),
        "title": item.title,
        "sub_title": item.sub_title,
        "developer": item.developer,
        "publisher": item.publisher,
        "release_date": item.release_date,
        "tags": cleaned_tags,
        "description": item.synopsis,
        "bangumi_id": resolved_bgm_id,
        "is_nsfw": bool(item.is_nsfw),
    }
