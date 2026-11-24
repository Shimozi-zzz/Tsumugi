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
from backend.core.scraper_settings import (
    ALL_CREDENTIAL_FIELDS,
    SECRET_CREDENTIAL_FIELDS,
    is_masked_placeholder,
    load_scraper_settings,
    sanitize_touchgal_token,
)
from backend.db.database import AsyncSessionLocal, get_db
from backend.db.models import AppStateSetting, Game, GameMediaPath, PlayRecord
from backend.schemas import (
    AggregateRequest,
    AssetApplyRequest,
    GameOut,
    MusicDownloadRequest,
    ScraperEnrichRequest,
    ScraperImportRequest,
    ScraperTestRequest,
)
from backend.scrapers.aggregator import MetadataAggregator
from backend.scrapers.asset_search import (
    download_pv_to_local,
    search_asset_candidates,
)
from backend.scrapers.bangumi import BANGUMI_USER_AGENT, BGM_BASE_URL
from backend.scrapers.base import (
    ScraperSearchResult,
    canonicalize_source_name,
    clean_scraped_tags,
    normalize_external_ids,
    normalize_platform_badge,
    normalize_search_text,
)
from backend.scrapers.manager import ScraperManager
from backend.scrapers.music import (
    download_op_music,
    resolve_preview_stream,
    search_op_music,
)
from backend.scrapers.steam import fetch_steam_trailers
from backend.services.asset_downloader import (
    _build_asset_headers,
    download_game_assets,
    download_single_image_asset,
)
from backend.services.media_service import (
    delete_local_media_cache,
    direct_video_extension,
    format_download_error_zh,
    generate_pinyin_initials,
    is_remote_http_url,
)
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
    fallback_urls: list[str] | None = None,
    steam_appid: str = "",
) -> None:
    """后台异步下载宣传片至 data/assets/{game_id}/pv.{ext}，保留远程链接以支持失败即时回退在线播放"""
    resolved_fallbacks: list[str] = list(fallback_urls or [])
    if (
        steam_appid
        and not direct_video_extension(url, mime_hint)
        and not any(direct_video_extension(u) for u in resolved_fallbacks)
    ):
        try:
            trailers = await fetch_steam_trailers(steam_appid, proxy_url=proxy_url)
            for tr in trailers:
                for cand_u in [tr.get("url"), *(tr.get("fallback_urls") or [])]:
                    if cand_u and direct_video_extension(str(cand_u)) and str(cand_u) not in resolved_fallbacks:
                        resolved_fallbacks.append(str(cand_u))
        except Exception:
            pass

    try:
        rel_path = await download_pv_to_local(
            game_id=game_id,
            url=url,
            proxy_url=proxy_url,
            mime_hint=mime_hint,
            fallback_urls=resolved_fallbacks,
        )
        async with AsyncSessionLocal() as db:
            stmt = select(Game).where(Game.id == game_id).options(selectinload(Game.media))
            game = (await db.execute(stmt)).scalar_one_or_none()
            if game and game.media:
                game.media.pv_url_or_path = rel_path
                if not game.media.pv_remote_url and is_remote_http_url(url):
                    game.media.pv_remote_url = url
                game.media.pv_mode = "download"
                await db.commit()
    except Exception as exc:
        logger.warning("Background PV download failed for game_id=%s url=%s: %s", game_id, url, exc)


async def _background_download_selected_bgm(
    game_id: int,
    bgm_url: str,
    proxy_url: str,
) -> None:
    """后台异步下载用户选中的主题曲原声至 data/assets/{game_id}/bgm.{ext}，失败保留在线链接"""
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
                if not game.media.bgm_remote_url and is_remote_http_url(bgm_url):
                    game.media.bgm_remote_url = bgm_url
                game.media.bgm_mode = "download"
                await db.commit()
        task_manager.mark_done(game_id, "bgm", "主题曲已缓存到本地")
    except Exception as exc:
        logger.error("Background selected BGM download failed for game_id=%s: %s", game_id, exc, exc_info=True)
        zh_msg = format_download_error_zh(exc, media_kind="audio")
        task_manager.mark_error(game_id, "bgm", zh_msg)


async def _background_auto_fetch_bgm(
    game_id: int,
    query: str,
    proxy_url: str,
    mode: Literal["link_only", "download"] = "download",
) -> None:
    """后台静默匹配一首最相关 OP 原声；link_only 仅保存链接不下载，download 缓存至本地"""
    if mode == "download":
        task_manager.set_task(game_id, "bgm", "downloading", 10, "正在匹配主题曲…")
    try:
        candidates = await search_op_music(query, proxy_url=proxy_url)
        if not candidates:
            if mode == "download":
                task_manager.mark_error(game_id, "bgm", "未匹配到可用主题曲")
            return
        best = candidates[0]
        src_url = str(best.get("source_url") or "").strip()
        prev_url = str(best.get("preview_url") or "").strip()
        remote_url = prev_url or src_url

        if mode == "link_only":
            if remote_url:
                async with AsyncSessionLocal() as db:
                    stmt = select(Game).where(Game.id == game_id).options(selectinload(Game.media))
                    game = (await db.execute(stmt)).scalar_one_or_none()
                    if game and game.media and not game.media.bgm_path:
                        game.media.bgm_remote_url = remote_url
                        game.media.bgm_path = remote_url
                        game.media.bgm_mode = "link_only"
                        await db.commit()
            return

        # download 模式：先保留在线链接，再下载缓存至本地
        if remote_url:
            async with AsyncSessionLocal() as db:
                stmt = select(Game).where(Game.id == game_id).options(selectinload(Game.media))
                game = (await db.execute(stmt)).scalar_one_or_none()
                if game and game.media:
                    game.media.bgm_remote_url = remote_url
                    if not game.media.bgm_path:
                        game.media.bgm_path = remote_url
                    game.media.bgm_mode = "download"
                    await db.commit()

        task_manager.update_progress(game_id, "bgm", 45, "正在下载主题曲…")
        rel_path = await download_op_music(
            game_id=game_id,
            source_url=src_url,
            preview_url=prev_url,
            proxy_url=proxy_url,
        )
        async with AsyncSessionLocal() as db:
            stmt = select(Game).where(Game.id == game_id).options(selectinload(Game.media))
            game = (await db.execute(stmt)).scalar_one_or_none()
            if game and game.media:
                game.media.bgm_path = rel_path
                game.media.bgm_mode = "download"
                await db.commit()
        task_manager.mark_done(game_id, "bgm", "主题曲已缓存到本地")
    except Exception as exc:
        logger.error("Background auto_fetch_bgm failed for game_id=%s: %s", game_id, exc, exc_info=True)
        if mode == "download":
            zh_msg = format_download_error_zh(exc, media_kind="audio")
            task_manager.mark_error(game_id, "bgm", zh_msg)


async def _load_scraper_context(
    db: AsyncSession,
) -> tuple[ScraperManager, MetadataAggregator, dict[str, Any], dict[str, Any]]:
    result = await db.execute(select(AppStateSetting))
    stored = {row.key: row.value for row in result.scalars().all()}
    cfg = {**DEFAULT_SETTINGS, **stored}

    proxy_url = str(cfg.get("proxy_url") or "")
    allow_nsfw = bool(cfg.get("allow_nsfw_scrape", True))
    scraper_cfg = load_scraper_settings(db_cfg=cfg)

    api_keys = dict(cfg.get("api_keys")) if isinstance(cfg.get("api_keys"), dict) else {}
    api_keys["bangumi"] = str(scraper_cfg.get("bangumi_token") or resolve_bangumi_token(cfg) or "")
    api_keys["touchgal"] = str(scraper_cfg.get("touchgal_api_key") or api_keys.get("touchgal") or "")
    api_keys["steamgriddb"] = str(scraper_cfg.get("steamgriddb_api_key") or api_keys.get("steamgriddb") or "")
    api_keys["ymgal_client_id"] = str(scraper_cfg.get("ymgal_client_id") or "")
    api_keys["ymgal_client_secret"] = str(scraper_cfg.get("ymgal_client_secret") or "")
    api_keys["kungal_base_url"] = str(scraper_cfg.get("kungal_base_url") or "")
    api_keys["kungal_token"] = str(scraper_cfg.get("kungal_token") or "")
    api_keys["igdb_client_id"] = str(scraper_cfg.get("igdb_client_id") or "")
    api_keys["igdb_client_secret"] = str(scraper_cfg.get("igdb_client_secret") or "")
    cfg["api_keys"] = api_keys

    aggregator = MetadataAggregator(
        proxy_url=proxy_url,
        api_keys=api_keys,
        allow_nsfw=allow_nsfw,
        scraper_settings=scraper_cfg,
    )
    return aggregator.manager, aggregator, cfg, scraper_cfg


async def _load_aggregator(db: AsyncSession) -> tuple[MetadataAggregator, dict[str, Any]]:
    _, aggregator, cfg, _ = await _load_scraper_context(db)
    return aggregator, cfg


async def _annotate_library_status(
    db: AsyncSession,
    items: list[ScraperSearchResult],
) -> None:
    """对照本地游戏库（外站 ID + 归一化标题），标注候选条目的已入库状态防止重复导入"""
    if not items:
        return

    rows = (
        await db.execute(
            select(Game.id, Game.title, Game.sub_title, Game.bangumi_id, Game.external_ids)
        )
    ).all()

    by_ext: dict[tuple[str, str], int] = {}
    by_title: dict[str, int] = {}

    for gid, g_title, g_sub, g_bgm, g_ext in rows:
        ext_map = normalize_external_ids(g_ext if isinstance(g_ext, dict) else {})
        if g_bgm and "bangumi" not in ext_map:
            ext_map["bangumi"] = str(g_bgm).strip()
        for k, v in ext_map.items():
            if v:
                by_ext[(k, v.lower())] = gid
        for t in (g_title, g_sub):
            nt = normalize_search_text(t)
            if nt and len(nt) >= 2 and nt not in by_title:
                by_title[nt] = gid

    for item in items:
        matched_gid: int | None = None
        cand_ext = normalize_external_ids(item.external_ids)
        norm_src = canonicalize_source_name(item.source)
        if item.source_id and norm_src and norm_src not in cand_ext:
            cand_ext[norm_src] = item.source_id

        for k, v in cand_ext.items():
            if (k, v.lower()) in by_ext:
                matched_gid = by_ext[(k, v.lower())]
                break

        if matched_gid is None:
            for t in (item.title, item.original_title, *(item.aliases or [])):
                nt = normalize_search_text(t)
                if nt and nt in by_title:
                    matched_gid = by_title[nt]
                    break

        if matched_gid is not None:
            item.already_in_library = True
            item.existing_game_id = matched_gid


def _parse_sources_query(
    sources: list[str] | None,
    legacy_source: str | None,
) -> list[str] | None:
    parsed: list[str] = []
    if sources:
        for raw in sources:
            for part in str(raw or "").split(","):
                s = part.strip().lower()
                if s and s not in ("all", "aggregated"):
                    parsed.append(s)
    elif legacy_source:
        ls = legacy_source.strip().lower()
        if ls and ls not in ("all", "aggregated"):
            for part in ls.split(","):
                s = part.strip().lower()
                if s and s not in ("all", "aggregated"):
                    parsed.append(s)
    return list(dict.fromkeys(parsed)) if parsed else None


async def _set_last_active(db: AsyncSession, game_id: int) -> None:
    setting = await db.get(AppStateSetting, "last_active_game_id")
    if setting:
        setting.value = game_id
    else:
        db.add(AppStateSetting(key="last_active_game_id", value=game_id))


@router.get("/sources")
async def list_scraper_sources(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """返回全部注册元数据刮削器的启用状态、Key 配置状态与元信息"""
    manager, _, _, _ = await _load_scraper_context(db)
    descriptors = manager.list_source_descriptors()
    return {
        "sources": descriptors,
        "sgdb_configured": manager.is_source_available("steamgriddb"),
        "igdb_configured": manager.is_source_available("igdb"),
        "touchgal_configured": manager.is_source_available("touchgal"),
    }


@router.post("/test/{source}")
async def test_scraper_source(
    source: str,
    payload: ScraperTestRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """测试单个数据源连通性（超时 6s，支持传入未保存的临时凭证提前验证）"""
    _, _, cfg, scraper_cfg = await _load_scraper_context(db)
    effective_cfg = dict(scraper_cfg)

    if payload is not None:
        overrides = payload.model_dump(exclude_unset=True)
        for field in ALL_CREDENTIAL_FIELDS:
            if field not in overrides or overrides[field] is None:
                continue
            val = str(overrides[field]).strip()
            if field in SECRET_CREDENTIAL_FIELDS and is_masked_placeholder(val):
                continue
            if field == "touchgal_api_key":
                val = sanitize_touchgal_token(val)
            if val:
                effective_cfg[field] = val

    manager = ScraperManager(
        proxy_url=str(cfg.get("proxy_url") or ""),
        allow_nsfw=bool(cfg.get("allow_nsfw_scrape", True)),
        scraper_settings=effective_cfg,
    )
    if not manager.get_scraper(source):
        raise HTTPException(status_code=400, detail=f"不支持的数据源: {source}")
    return await manager.test_source(source, timeout=6.0)


@router.get("/search")
async def search_metadata(
    q: str = Query(..., min_length=1, description="游戏搜索关键词、作品链接或编号"),
    category: Literal["all", "galgame", "general"] | None = Query(
        None,
        description="可选兼容参数（省略时默认综合推荐并发全部已启用数据源）",
    ),
    sources: list[str] | None = Query(
        None,
        description="指定单源或多源数组（省略时并发全部已启用数据源）",
    ),
    source: str | None = Query(
        None,
        description="向后兼容单源参数: aggregated / ymgal / kungal / dlsite / vndb / bangumi / bgm / steam / igdb / sgdb / tgal",
    ),
    limit: int = Query(15, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """多源并发容错检索（默认综合推荐全源并发、支持链接/编号直查、去重相关性重排与已入库标注）"""
    manager, _, _, _ = await _load_scraper_context(db)
    resolved_sources = _parse_sources_query(sources, source)

    if resolved_sources:
        for sid in resolved_sources:
            if not manager.get_scraper(sid):
                raise HTTPException(status_code=400, detail=f"不支持的刮削源: {sid}")

    search_res = await manager.search(
        q,
        category=category or "all",
        sources=resolved_sources,
        limit=limit,
    )
    items: list[ScraperSearchResult] = search_res["items"]
    await _annotate_library_status(db, items)

    return {
        "source": (resolved_sources[0] if resolved_sources and len(resolved_sources) == 1 else "aggregated"),
        "category": search_res["category"],
        "sources": search_res["sources"],
        "query": q,
        "direct_match": search_res["direct_match"],
        "count": len(items),
        "sgdb_configured": manager.is_source_available("steamgriddb"),
        "igdb_configured": manager.is_source_available("igdb"),
        "touchgal_configured": manager.is_source_available("touchgal"),
        "available_sources": manager.list_source_descriptors(),
        "source_errors": search_res["source_errors"],
        "items": [it.to_api_dict() for it in items],
    }


@router.get("/detail/{source}/{external_id}")
async def get_source_detail(
    source: str,
    external_id: str,
    db: AsyncSession = Depends(get_db),
):
    """拉取单个平台的完整详情与视觉资产链接"""
    manager, _, _, _ = await _load_scraper_context(db)
    if not manager.get_scraper(source):
        raise HTTPException(status_code=400, detail=f"不支持的刮削源: {source}")

    detail = await manager.get_detail(source, external_id)
    if not detail:
        raise HTTPException(status_code=404, detail="未从该平台获取到有效详情")
    await _annotate_library_status(db, [detail])
    return detail.to_api_dict()


@router.post("/enrich")
async def enrich_metadata_cross_source(
    payload: ScraperEnrichRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """跨源字段补全：从其他源拉取中文简介、开发商/标签以及高清封面/背景（含 SteamGridDB）"""
    manager, _, _, _ = await _load_scraper_context(db)
    return await manager.enrich(
        title=payload.title,
        original_title=payload.original_title,
        aliases=payload.aliases,
        release_date=payload.release_date,
        source=payload.source,
        source_id=payload.source_id,
        external_ids=payload.external_ids,
        target_sources=payload.target_sources,
        mode=payload.mode,
    )


@router.post("/aggregate")
async def aggregate_preview(
    payload: AggregateRequest,
    db: AsyncSession = Depends(get_db),
):
    """并发调用所有可用源并按最优权重拼装元数据与高清视觉资产，供入库前预览微调"""
    _, aggregator, _, _ = await _load_scraper_context(db)
    res = await aggregator.aggregate_detail(
        keyword=payload.keyword,
        external_ids=payload.external_ids,
        preferred_source=payload.preferred_source,
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

    norm_external_ids = normalize_external_ids(payload.external_ids)
    resolved_bgm_id = _extract_bangumi_id(payload.bangumi_id, norm_external_ids)
    if resolved_bgm_id and "bangumi" not in norm_external_ids:
        norm_external_ids["bangumi"] = resolved_bgm_id

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
        source_platform=normalize_platform_badge(payload.source_platform, norm_external_ids),
        bangumi_id=resolved_bgm_id,
        external_ids=norm_external_ids,
        locked_fields=[],
    )

    # ── 1. 解析 PV 三模式策略：none / link_only / download ──
    selected_pv = (payload.selected_pv_url or "").strip()
    raw_pv = (payload.pv_url or "").strip()
    candidate_pv = selected_pv or raw_pv

    if payload.pv_mode is not None:
        resolved_pv_mode = payload.pv_mode
    else:
        resolved_pv_mode = "download" if candidate_pv else "none"

    pv_download_url = ""
    initial_pv_path = ""
    initial_pv_remote = ""
    if resolved_pv_mode == "none":
        initial_pv_path = ""
        initial_pv_remote = ""
    elif resolved_pv_mode == "link_only":
        if candidate_pv:
            initial_pv_path = candidate_pv
            initial_pv_remote = candidate_pv if is_remote_http_url(candidate_pv) else ""
        else:
            resolved_pv_mode = "none"
    else:  # download
        if is_remote_http_url(candidate_pv):
            # 先将远程链接写入数据库，下载成功后再替换为本地路径；即使下载失败也能零刷新直接在线播放
            pv_download_url = candidate_pv
            initial_pv_path = candidate_pv
            initial_pv_remote = candidate_pv
        elif candidate_pv:
            initial_pv_path = candidate_pv
            initial_pv_remote = ""
        else:
            resolved_pv_mode = "none"

    # ── 2. 解析 OP / BGM 三模式策略：none / link_only / download ──
    selected_bgm = (payload.selected_bgm_url or "").strip()
    if payload.op_mode is not None:
        resolved_op_mode = payload.op_mode
    else:
        resolved_op_mode = "download" if (selected_bgm or payload.auto_fetch_bgm) else "none"

    bgm_download_url = ""
    initial_bgm_path = ""
    initial_bgm_remote = ""
    should_auto_fetch_bgm = False

    if resolved_op_mode == "none":
        initial_bgm_path = ""
        initial_bgm_remote = ""
    elif resolved_op_mode == "link_only":
        if selected_bgm:
            initial_bgm_path = selected_bgm
            initial_bgm_remote = selected_bgm if is_remote_http_url(selected_bgm) else ""
        elif payload.auto_fetch_bgm:
            should_auto_fetch_bgm = True
        else:
            resolved_op_mode = "none"
    else:  # download
        if is_remote_http_url(selected_bgm):
            bgm_download_url = selected_bgm
            initial_bgm_path = selected_bgm
            initial_bgm_remote = selected_bgm
        elif selected_bgm:
            initial_bgm_path = selected_bgm
            initial_bgm_remote = ""
        elif payload.auto_fetch_bgm:
            should_auto_fetch_bgm = True
        else:
            resolved_op_mode = "none"

    game.media = GameMediaPath(
        exe_path=payload.exe_path.strip(),
        launch_mode=payload.launch_mode or "direct",
        launch_args=payload.launch_args.strip(),
        save_dir=payload.save_dir.strip(),
        screenshot_dir=payload.screenshot_dir.strip(),
        pv_url_or_path=initial_pv_path,
        pv_remote_url=initial_pv_remote,
        pv_mode=resolved_pv_mode,
        bgm_path=initial_bgm_path,
        bgm_remote_url=initial_bgm_remote,
        bgm_mode=resolved_op_mode,
    )
    game.play_record = PlayRecord(total_seconds=0)

    db.add(game)
    await db.flush()

    # 并发下载视觉图片资产并自动转为 WebP 及生成 420px 封面缩略图（PV/OP 按三模式策略单独处理）
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

    # 仅在 pv_mode == "download" 且存在远程链接时派发后台下载队列（link_only / none 绝不派发）
    if resolved_pv_mode == "download" and pv_download_url:
        task_manager.set_task(game.id, "pv", "queued", 0, "等待下载宣传片…")
        asyncio.create_task(
            _background_download_pv(
                game_id=game.id,
                url=pv_download_url,
                proxy_url=proxy_url,
                mime_hint=(payload.selected_pv_mime_hint or "").strip(),
                fallback_urls=list(payload.selected_pv_fallback_urls or []),
                steam_appid=str(norm_external_ids.get("steam") or ""),
            )
        )

    # 仅在 op_mode == "download"（或显式 auto_fetch_bgm）时派发 OP 后台任务
    if resolved_op_mode == "download" and bgm_download_url:
        task_manager.set_task(game.id, "bgm", "queued", 0, "等待下载主题曲…")
        asyncio.create_task(
            _background_download_selected_bgm(game.id, bgm_download_url, proxy_url)
        )
    elif should_auto_fetch_bgm:
        bgm_query = (payload.sub_title or payload.title).strip()
        if bgm_query:
            if resolved_op_mode == "download":
                task_manager.set_task(game.id, "bgm", "queued", 0, "等待匹配主题曲…")
            asyncio.create_task(
                _background_auto_fetch_bgm(
                    game.id,
                    bgm_query,
                    proxy_url,
                    mode="link_only" if resolved_op_mode == "link_only" else "download",
                )
            )

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
        new_pv_url = downloaded["pv_url_or_path"]
        if is_remote_http_url(new_pv_url):
            game.media.pv_remote_url = new_pv_url
            # 已有本地缓存视频时绝不被远程链接覆盖（始终优先保留本地视频）
            has_local_pv = bool(game.media.pv_url_or_path and not is_remote_http_url(game.media.pv_url_or_path))
            if not has_local_pv:
                game.media.pv_url_or_path = new_pv_url
                game.media.pv_mode = "link_only"
        else:
            game.media.pv_url_or_path = new_pv_url
            game.media.pv_mode = "download"
    if not game.media.screenshot_dir and downloaded.get("downloaded_screenshot_dir"):
        game.media.screenshot_dir = downloaded["downloaded_screenshot_dir"]

    await db.commit()
    refreshed = (await db.execute(stmt)).scalar_one()
    return refreshed


# ──────────────────── OP / 主题曲原声在线搜寻与下载 ────────────────────


@router.get("/music/search")
async def search_music_candidates(
    q: str = Query(..., min_length=1, description="游戏原名或中文名"),
    source: str = Query("auto", description="数据源: auto / bilibili / youtube / itunes"),
    alt_title: str = Query("", description="可选：作品别名/原名用于相关性过滤"),
    db: AsyncSession = Depends(get_db),
):
    """按平台分选或并发搜寻 Bilibili / YouTube 全曲 OP 与 iTunes JP 试听候选项"""
    _, cfg = await _load_aggregator(db)
    proxy_url = str(cfg.get("proxy_url") or "")
    items = await search_op_music(q, proxy_url=proxy_url, source=source, alt_title=alt_title)
    return {"query": q, "source": source, "count": len(items), "items": items}


@router.post("/music/download/{game_id}")
async def download_music_for_game(
    game_id: int,
    payload: MusicDownloadRequest,
    db: AsyncSession = Depends(get_db),
):
    """按三模式（link_only / download / none）绑定或下载 OP 原声至本地"""
    stmt = select(Game).where(Game.id == game_id).options(selectinload(Game.media))
    game = (await db.execute(stmt)).scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    if not game.media:
        game.media = GameMediaPath(game_id=game.id)

    if payload.mode == "none":
        delete_local_media_cache(game_id, "bgm")
        game.media.bgm_path = ""
        game.media.bgm_remote_url = ""
        game.media.bgm_mode = "none"
        await db.commit()
        return {"game_id": game_id, "bgm_path": "", "bgm_remote_url": "", "bgm_mode": "none"}

    target_remote = (payload.preview_url or payload.source_url or "").strip()
    if not target_remote:
        raise HTTPException(status_code=400, detail="请提供有效的音频来源链接")

    if payload.mode == "link_only":
        delete_local_media_cache(game_id, "bgm")
        game.media.bgm_remote_url = target_remote if is_remote_http_url(target_remote) else ""
        game.media.bgm_path = target_remote
        game.media.bgm_mode = "link_only"
        await db.commit()
        return {
            "game_id": game_id,
            "bgm_path": game.media.bgm_path,
            "bgm_remote_url": game.media.bgm_remote_url,
            "bgm_mode": "link_only",
        }

    _, cfg = await _load_aggregator(db)
    proxy_url = str(cfg.get("proxy_url") or "")

    # download 模式：先持久化远程链接确保失败也可在线回退播放
    if is_remote_http_url(target_remote):
        game.media.bgm_remote_url = target_remote
        if not game.media.bgm_path:
            game.media.bgm_path = target_remote
    game.media.bgm_mode = "download"
    await db.commit()

    if payload.async_mode:
        task_info = task_manager.set_task(game_id, "bgm", "queued", 0, "等待下载主题曲…")
        asyncio.create_task(_background_download_selected_bgm(game_id, target_remote, proxy_url))
        return {
            "game_id": game_id,
            "bgm_path": game.media.bgm_path,
            "bgm_remote_url": game.media.bgm_remote_url,
            "bgm_mode": "download",
            "download_task": task_info,
        }

    try:
        rel_path = await download_op_music(
            game_id=game_id,
            source_url=payload.source_url,
            preview_url=payload.preview_url,
            proxy_url=proxy_url,
        )
    except Exception as exc:
        logger.error("Sync OP music download failed for game_id=%s: %s", game_id, exc, exc_info=True)
        raise HTTPException(status_code=400, detail=format_download_error_zh(exc, media_kind="audio"))

    game.media.bgm_path = rel_path
    game.media.bgm_mode = "download"
    await db.commit()
    return {
        "game_id": game_id,
        "bgm_path": rel_path,
        "bgm_remote_url": game.media.bgm_remote_url,
        "bgm_mode": "download",
    }


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
        logger.warning("Music preview resolve failed for %s: %s", url, exc)
        raise HTTPException(status_code=400, detail=format_download_error_zh(exc, media_kind="audio"))

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
    q: str = Query("", description="检索关键词"),
    source: str = Query(
        "all",
        description="数据源: auto / all / steamgriddb / vndb / bangumi / steam / touchgal / bilibili / youtube / video",
    ),
    steam_appid: str = Query("", description="可选：已知 Steam AppID，用于优先拉取官方 PV"),
    alt_title: str = Query("", description="可选：游戏原名或中文名，辅助精确匹配与相关性过滤"),
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
        steam_appid=steam_appid,
        alt_title=alt_title,
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
        if payload.mode == "none":
            delete_local_media_cache(game_id, "pv")
            game.media.pv_url_or_path = ""
            game.media.pv_remote_url = ""
            game.media.pv_mode = "none"
            await db.commit()
            refreshed = (await db.execute(stmt)).scalar_one()
            return GameOut.model_validate(refreshed)

        if payload.mode == "link_only":
            delete_local_media_cache(game_id, "pv")
            game.media.pv_url_or_path = target_url
            game.media.pv_remote_url = target_url if is_remote_http_url(target_url) else ""
            game.media.pv_mode = "link_only"
            await db.commit()
            refreshed = (await db.execute(stmt)).scalar_one()
            return GameOut.model_validate(refreshed)

        # download 模式：先持久化远程链接，即使后台下载失败也可直接无刷新在线回退播放
        if is_remote_http_url(target_url):
            game.media.pv_remote_url = target_url
            game.media.pv_url_or_path = target_url
        game.media.pv_mode = "download"
        await db.commit()

        steam_appid = str((game.external_ids or {}).get("steam") or "")
        if payload.async_mode:
            task_info = task_manager.set_task(game_id, "pv", "queued", 0, "等待下载宣传片…")
            asyncio.create_task(
                _background_download_pv(
                    game_id=game_id,
                    url=target_url,
                    proxy_url=proxy_url,
                    mime_hint=payload.mime_hint,
                    fallback_urls=list(payload.fallback_urls or []),
                    steam_appid=steam_appid,
                )
            )
            refreshed = (await db.execute(stmt)).scalar_one()
            game_data = GameOut.model_validate(refreshed).model_dump(mode="json")
            return {**game_data, "download_task": task_info}

        try:
            rel_path = await download_pv_to_local(
                game_id=game_id,
                url=target_url,
                proxy_url=proxy_url,
                mime_hint=payload.mime_hint,
                fallback_urls=list(payload.fallback_urls or []),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=format_download_error_zh(exc, media_kind="video"))
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

    raw_tok = (token or "").strip() or (x_bangumi_token or "").strip()
    if is_masked_placeholder(raw_tok):
        raw_tok = ""
    resolved_token = raw_tok or resolve_bangumi_token(cfg)
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
    source: Literal[
        "ymgal", "kungal", "dlsite", "bangumi", "vndb", "steam", "igdb", "touchgal"
    ] = Query(
        ...,
        description="单一数据源: ymgal / kungal / dlsite / bangumi / vndb / steam / igdb / touchgal",
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
    source: Literal[
        "ymgal", "kungal", "dlsite", "bangumi", "vndb", "steam", "igdb", "touchgal"
    ] = Query(
        ...,
        description="单一数据源: ymgal / kungal / dlsite / bangumi / vndb / steam / igdb / touchgal",
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
