import asyncio
import hashlib
import logging
import os
from pathlib import Path
import shutil
from typing import Any, Literal
from urllib.parse import quote, urlparse

import httpx
from pydantic import BaseModel
import yt_dlp

from backend.core.config import ASSETS_DIR, DATA_DIR
from backend.scrapers.bangumi import BangumiScraper
from backend.scrapers.bilibili import (
    BILIBILI_REFERER,
    BILIBILI_USER_AGENT,
    search_bilibili_videos,
)
from backend.scrapers.dlsite import DLsiteScraper
from backend.scrapers.igdb import IGDBScraper
from backend.scrapers.kungal import KungalScraper
from backend.scrapers.steam import (
    STEAM_CDN_BASE,
    STEAM_DETAIL_URL,
    STEAM_SEARCH_URL,
    SteamScraper,
    fetch_steam_trailers,
    match_steam_appid,
)
from backend.scrapers.steamgriddb import SGDB_API_BASE, SteamGridDBScraper
from backend.scrapers.touchgal import TouchGalScraper
from backend.scrapers.vndb import VNDB_API_URL, VNDBScraper
from backend.scrapers.ymgal import YMGalScraper
from backend.services.media_service import (
    download_pv_to_local as _media_download_pv_to_local,
)
from backend.services.task_manager import task_manager

logger = logging.getLogger("tsumugi.scrapers.asset_search")

AssetType = Literal["cover", "logo", "hero", "spine", "pv"]

PV_MIN_DURATION_SEC = 30
PV_MAX_DURATION_SEC = 360
PV_SEARCH_TIMEOUT_SEC = 12.0
DIRECT_VIDEO_EXTS = {".m3u8", ".mp4", ".webm"}
SAVED_VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}

SOURCE_ALIASES: dict[str, str] = {
    "all": "all",
    "auto": "auto",
    "steamgriddb": "steamgriddb",
    "sgdb": "steamgriddb",
    "vndb": "vndb",
    "bangumi": "bangumi",
    "bgm": "bangumi",
    "steam": "steam",
    "ymgal": "ymgal",
    "kungal": "kungal",
    "dlsite": "dlsite",
    "igdb": "igdb",
    "touchgal": "touchgal",
    "tgal": "touchgal",
    "video": "video",
    "bilibili": "bilibili",
    "youtube": "youtube",
}


class _SilentYdlLogger:
    def debug(self, _msg: str) -> None:
        pass

    def warning(self, _msg: str) -> None:
        pass

    def error(self, _msg: str) -> None:
        pass


_SILENT_YDL_LOGGER = _SilentYdlLogger()


class AssetCandidate(BaseModel):
    """单项视觉资产 / 宣传片统一候选模型"""

    id: str
    url: str
    fallback_urls: list[str] = []
    thumb_url: str
    source: str
    platform: str = ""
    is_official: bool = False
    title: str
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    mime_hint: str = "image"


def _make_id(source: str, url: str) -> str:
    digest = hashlib.sha1(f"{source}:{url}".encode("utf-8")).hexdigest()[:12]
    return f"{source.lower()}-{digest}"


def _normalize_url(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if s.startswith("//"):
        return f"https:{s}"
    return s


def _safe_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        n = int(round(float(val)))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _parse_dims(dims: Any) -> tuple[int | None, int | None]:
    if isinstance(dims, (list, tuple)) and len(dims) >= 2:
        return _safe_int(dims[0]), _safe_int(dims[1])
    return None, None


def _extract_vndb_title(entry: dict[str, Any]) -> str:
    default_title = str(entry.get("title") or "").strip()
    alt_title = str(entry.get("alttitle") or "").strip()
    zh_title = ""
    for t in entry.get("titles") or []:
        lang = str(t.get("lang") or "").lower()
        t_str = str(t.get("title") or "").strip()
        if not t_str:
            continue
        if lang == "zh-hans" and not zh_title:
            zh_title = t_str
        elif lang == "zh-hant" and not zh_title:
            zh_title = t_str
    return zh_title or default_title or alt_title or str(entry.get("id") or "")


# ──────────────────── SteamGridDB 多候选拉取 ────────────────────


async def _fetch_sgdb_candidates(
    asset_type: AssetType,
    query: str,
    scraper: SteamGridDBScraper,
    steam_appid: str = "",
) -> tuple[list[AssetCandidate], list[str]]:
    if not scraper.api_key:
        return [], ["尚未配置 SteamGridDB API Key，可在全局设置 -> 元数据刮削源中填写"]

    if asset_type == "pv":
        return [], []

    nsfw = scraper._nsfw_param()
    endpoint_map: dict[str, tuple[str, dict[str, Any]]] = {
        "cover": ("grids", {"dimensions": "600x900,342x482", "nsfw": nsfw, "limit": 12}),
        "spine": ("grids", {"dimensions": "600x900,342x482", "nsfw": nsfw, "limit": 12}),
        "logo": ("logos", {"nsfw": nsfw, "limit": 12}),
        "hero": ("heroes", {"nsfw": nsfw, "limit": 12}),
    }
    kind, params = endpoint_map[asset_type]

    try:
        async with scraper._build_client(headers=scraper._auth_headers(), timeout=12.0) as client:
            games: list[dict[str, Any]] = []
            if steam_appid and steam_appid.strip().isdigit():
                by_steam = await client.get(f"{SGDB_API_BASE}/games/steam/{steam_appid.strip()}")
                if by_steam.status_code == 200:
                    g = by_steam.json().get("data")
                    if isinstance(g, dict) and g.get("id"):
                        games.append(g)

            if not games and query:
                search_resp = await client.get(f"{SGDB_API_BASE}/search/autocomplete/{quote(query)}")
                if search_resp.status_code == 200:
                    games = search_resp.json().get("data") or []
            if not games:
                return [], []

            candidates: list[AssetCandidate] = []
            seen_urls: set[str] = set()

            for g in games[:2]:
                sgdb_id = str(g.get("id") or "").strip()
                game_title = str(g.get("name") or query).strip()
                if not sgdb_id:
                    continue

                resp = await client.get(f"{SGDB_API_BASE}/{kind}/game/{sgdb_id}", params=params)
                if resp.status_code != 200:
                    continue
                items = resp.json().get("data") or []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    mime = str(it.get("mime") or "").lower()
                    if mime and mime not in ("image/png", "image/webp", "image/jpeg"):
                        continue
                    url = _normalize_url(it.get("url"))
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    thumb = _normalize_url(it.get("thumb")) or url
                    candidates.append(
                        AssetCandidate(
                            id=_make_id("SteamGridDB", url),
                            url=url,
                            thumb_url=thumb,
                            source="SteamGridDB",
                            title=game_title,
                            width=_safe_int(it.get("width")),
                            height=_safe_int(it.get("height")),
                            mime_hint="image",
                        )
                    )
                    if len(candidates) >= 12:
                        return candidates, []

                if len(candidates) >= 6:
                    break

            return candidates, []
    except Exception as exc:
        logger.debug("SteamGridDB asset search (%s) failed for %r: %s", asset_type, query, exc)
        return [], []


# ──────────────────── VNDB 多候选拉取 ────────────────────


async def _fetch_vndb_candidates(
    asset_type: AssetType,
    query: str,
    scraper: VNDBScraper,
) -> list[AssetCandidate]:
    if asset_type not in ("cover", "spine", "hero"):
        return []

    fields = (
        "id, title, alttitle, titles.lang, titles.title, "
        "image.url, image.thumbnail, image.dims, image.sexual, image.violence"
        if asset_type in ("cover", "spine")
        else (
            "id, title, alttitle, titles.lang, titles.title, "
            "screenshots.url, screenshots.thumbnail, screenshots.dims, "
            "screenshots.sexual, screenshots.violence"
        )
    )
    payload = {
        "filters": ["search", "=", query],
        "fields": fields,
        "sort": "searchrank",
        "results": 8 if asset_type in ("cover", "spine") else 4,
    }

    try:
        async with scraper._build_client(timeout=12.0) as client:
            resp = await client.post(VNDB_API_URL, json=payload)
            if resp.status_code != 200:
                return []
            entries = resp.json().get("results") or []
    except Exception as exc:
        logger.debug("VNDB asset search (%s) failed for %r: %s", asset_type, query, exc)
        return []

    candidates: list[AssetCandidate] = []
    seen_urls: set[str] = set()

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = _extract_vndb_title(entry)
        if asset_type in ("cover", "spine"):
            img = entry.get("image") or {}
            url = _normalize_url(img.get("url"))
            if not url or url in seen_urls:
                continue
            sexual = float(img.get("sexual") or 0)
            violence = float(img.get("violence") or 0)
            if not scraper.allow_nsfw and (sexual >= 1.0 or violence >= 1.0):
                continue
            seen_urls.add(url)
            w, h = _parse_dims(img.get("dims"))
            thumb = _normalize_url(img.get("thumbnail")) or url
            candidates.append(
                AssetCandidate(
                    id=_make_id("VNDB", url),
                    url=url,
                    thumb_url=thumb,
                    source="VNDB",
                    title=title,
                    width=w,
                    height=h,
                    mime_hint="image",
                )
            )
        else:
            for ss in entry.get("screenshots") or []:
                if not isinstance(ss, dict):
                    continue
                url = _normalize_url(ss.get("url"))
                if not url or url in seen_urls:
                    continue
                sexual = float(ss.get("sexual") or 0)
                violence = float(ss.get("violence") or 0)
                if not scraper.allow_nsfw and (sexual >= 1.0 or violence >= 1.0):
                    continue
                seen_urls.add(url)
                w, h = _parse_dims(ss.get("dims"))
                thumb = _normalize_url(ss.get("thumbnail")) or url
                candidates.append(
                    AssetCandidate(
                        id=_make_id("VNDB", url),
                        url=url,
                        thumb_url=thumb,
                        source="VNDB",
                        title=title,
                        width=w,
                        height=h,
                        mime_hint="image",
                    )
                )
                if len(candidates) >= 12:
                    return candidates

    return candidates


# ──────────────────── Bangumi 多候选拉取 ────────────────────


async def _fetch_bangumi_candidates(
    asset_type: AssetType,
    query: str,
    scraper: BangumiScraper,
) -> list[AssetCandidate]:
    if asset_type not in ("cover", "spine"):
        return []

    items = await scraper.search(query, limit=10)
    candidates: list[AssetCandidate] = []
    seen_urls: set[str] = set()
    for it in items:
        url = _normalize_url(it.cover_url)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        candidates.append(
            AssetCandidate(
                id=_make_id("Bangumi", url),
                url=url,
                thumb_url=url,
                source="Bangumi",
                title=it.title,
                mime_hint="image",
            )
        )
    return candidates


# ──────────────────── Steam 多候选拉取 ────────────────────


async def _steam_search_apps(client, query: str, limit: int = 5) -> list[dict[str, Any]]:
    resp = await client.get(
        STEAM_SEARCH_URL,
        params={"term": query, "l": "schinese", "cc": "CN"},
    )
    resp.raise_for_status()
    items = resp.json().get("items") or []
    if not items:
        resp = await client.get(
            STEAM_SEARCH_URL,
            params={"term": query, "l": "schinese", "cc": "US"},
        )
        resp.raise_for_status()
        items = resp.json().get("items") or []
    return items[:limit]


async def _steam_appdetails(client, appid: str) -> dict[str, Any] | None:
    try:
        resp = await client.get(
            STEAM_DETAIL_URL,
            params={"appids": appid, "l": "schinese", "cc": "CN"},
        )
        resp.raise_for_status()
        block = (resp.json().get(appid) or {})
        if not block.get("success"):
            resp = await client.get(
                STEAM_DETAIL_URL,
                params={"appids": appid, "l": "schinese", "cc": "US"},
            )
            resp.raise_for_status()
            block = (resp.json().get(appid) or {})
        if block.get("success") and isinstance(block.get("data"), dict):
            return block["data"]
    except Exception:
        return None
    return None


async def _fetch_steam_candidates(
    asset_type: AssetType,
    query: str,
    scraper: SteamScraper,
) -> list[AssetCandidate]:
    try:
        async with scraper._build_client(timeout=12.0) as client:
            apps = await _steam_search_apps(
                client,
                query,
                limit=5 if asset_type in ("cover", "spine", "logo") else 3,
            )
            if not apps:
                return []

            candidates: list[AssetCandidate] = []
            seen_urls: set[str] = set()

            if asset_type in ("cover", "spine"):
                async def _probe_cover(entry: dict[str, Any]) -> list[AssetCandidate]:
                    appid = str(entry.get("id") or "").strip()
                    name = str(entry.get("name") or appid).strip()
                    if not appid:
                        return []
                    out: list[AssetCandidate] = []
                    v2 = f"{STEAM_CDN_BASE}/{appid}/library_600x900_2x.jpg"
                    v1 = f"{STEAM_CDN_BASE}/{appid}/library_600x900.jpg"
                    hdr = f"{STEAM_CDN_BASE}/{appid}/header.jpg"
                    ok_v2, ok_v1, ok_hdr = await asyncio.gather(
                        scraper._check_url_exists(client, v2),
                        scraper._check_url_exists(client, v1),
                        scraper._check_url_exists(client, hdr),
                    )
                    if ok_v2:
                        out.append(
                            AssetCandidate(
                                id=_make_id("Steam", v2),
                                url=v2,
                                thumb_url=v2,
                                source="Steam",
                                title=name,
                                width=600,
                                height=900,
                                mime_hint="image",
                            )
                        )
                    elif ok_v1:
                        out.append(
                            AssetCandidate(
                                id=_make_id("Steam", v1),
                                url=v1,
                                thumb_url=v1,
                                source="Steam",
                                title=name,
                                width=300,
                                height=450,
                                mime_hint="image",
                            )
                        )
                    header_url = hdr if ok_hdr else _normalize_url(entry.get("tiny_image"))
                    if header_url:
                        out.append(
                            AssetCandidate(
                                id=_make_id("Steam", header_url),
                                url=header_url,
                                thumb_url=header_url,
                                source="Steam",
                                title=f"{name} (头图)",
                                width=460 if ok_hdr else None,
                                height=215 if ok_hdr else None,
                                mime_hint="image",
                            )
                        )
                    return out

                batches = await asyncio.gather(*[_probe_cover(a) for a in apps], return_exceptions=True)
                for batch in batches:
                    if isinstance(batch, list):
                        for item in batch:
                            if item.url not in seen_urls:
                                seen_urls.add(item.url)
                                candidates.append(item)
                return candidates[:10]

            if asset_type == "logo":
                async def _probe_logo(entry: dict[str, Any]) -> AssetCandidate | None:
                    appid = str(entry.get("id") or "").strip()
                    name = str(entry.get("name") or appid).strip()
                    if not appid:
                        return None
                    logo_url = f"{STEAM_CDN_BASE}/{appid}/logo.png"
                    if await scraper._check_url_exists(client, logo_url):
                        return AssetCandidate(
                            id=_make_id("Steam", logo_url),
                            url=logo_url,
                            thumb_url=logo_url,
                            source="Steam",
                            title=name,
                            mime_hint="image",
                        )
                    return None

                found = await asyncio.gather(*[_probe_logo(a) for a in apps[:4]], return_exceptions=True)
                for item in found:
                    if isinstance(item, AssetCandidate) and item.url not in seen_urls:
                        seen_urls.add(item.url)
                        candidates.append(item)
                return candidates

            if asset_type == "hero":
                details = await asyncio.gather(
                    *[_steam_appdetails(client, str(a.get("id") or "")) for a in apps[:3]],
                    return_exceptions=True,
                )
                for app_entry, info in zip(apps[:3], details):
                    appid = str(app_entry.get("id") or "").strip()
                    name = (
                        str(info.get("name") or app_entry.get("name") or appid).strip()
                        if isinstance(info, dict)
                        else str(app_entry.get("name") or appid).strip()
                    )
                    if not appid:
                        continue
                    hero_url = f"{STEAM_CDN_BASE}/{appid}/library_hero.jpg"
                    if hero_url not in seen_urls and await scraper._check_url_exists(client, hero_url):
                        seen_urls.add(hero_url)
                        candidates.append(
                            AssetCandidate(
                                id=_make_id("Steam", hero_url),
                                url=hero_url,
                                thumb_url=hero_url,
                                source="Steam",
                                title=f"{name} (Hero)",
                                mime_hint="image",
                            )
                        )
                    if isinstance(info, dict):
                        bg_url = _normalize_url(info.get("background_raw") or info.get("background"))
                        if bg_url and bg_url not in seen_urls:
                            seen_urls.add(bg_url)
                            candidates.append(
                                AssetCandidate(
                                    id=_make_id("Steam", bg_url),
                                    url=bg_url,
                                    thumb_url=bg_url,
                                    source="Steam",
                                    title=f"{name} (商店背景)",
                                    mime_hint="image",
                                )
                            )
                        for ss in (info.get("screenshots") or [])[:6]:
                            full = _normalize_url(ss.get("path_full") or ss.get("path_thumbnail"))
                            thumb = _normalize_url(ss.get("path_thumbnail") or full)
                            if not full or full in seen_urls:
                                continue
                            seen_urls.add(full)
                            candidates.append(
                                AssetCandidate(
                                    id=_make_id("Steam", full),
                                    url=full,
                                    thumb_url=thumb,
                                    source="Steam",
                                    title=name,
                                    mime_hint="image",
                                )
                            )
                            if len(candidates) >= 12:
                                return candidates
                return candidates[:12]

            if asset_type == "pv":
                details = await asyncio.gather(
                    *[_steam_appdetails(client, str(a.get("id") or "")) for a in apps[:3]],
                    return_exceptions=True,
                )
                for app_entry, info in zip(apps[:3], details):
                    if not isinstance(info, dict):
                        continue
                    app_name = str(info.get("name") or app_entry.get("name") or "").strip()
                    for movie in info.get("movies") or []:
                        if not isinstance(movie, dict):
                            continue
                        hls = _normalize_url(movie.get("hls_h264"))
                        mp4_obj = movie.get("mp4") or {}
                        webm_obj = movie.get("webm") or {}
                        mp4_url = _normalize_url(mp4_obj.get("max") or mp4_obj.get("480"))
                        webm_url = _normalize_url(webm_obj.get("max") or webm_obj.get("480"))

                        if mp4_url:
                            play_url, hint = mp4_url, "mp4"
                        elif hls:
                            play_url, hint = hls, "hls"
                        elif webm_url:
                            play_url, hint = webm_url, "mp4"
                        else:
                            continue

                        if play_url in seen_urls:
                            continue
                        seen_urls.add(play_url)
                        m_name = str(movie.get("name") or app_name or "官方宣传片").strip()
                        thumb = _normalize_url(movie.get("thumbnail"))
                        candidates.append(
                            AssetCandidate(
                                id=_make_id("Steam", play_url),
                                url=play_url,
                                thumb_url=thumb,
                                source="Steam",
                                title=m_name,
                                duration=None,
                                mime_hint=hint,
                            )
                        )
                        if len(candidates) >= 8:
                            return candidates
                return candidates

    except Exception as exc:
        logger.debug("Steam asset search (%s) failed for %r: %s", asset_type, query, exc)
        return []

    return []


# ──────────────────── TouchGal 多候选拉取 ────────────────────


async def _fetch_touchgal_candidates(
    asset_type: AssetType,
    query: str,
    scraper: TouchGalScraper,
) -> list[AssetCandidate]:
    if asset_type not in ("cover", "spine", "hero"):
        return []

    items = await scraper.search(query, limit=10)
    candidates: list[AssetCandidate] = []
    seen_urls: set[str] = set()
    for it in items:
        raw_url = it.background_url if asset_type == "hero" else it.cover_url
        url = _normalize_url(raw_url)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        candidates.append(
            AssetCandidate(
                id=_make_id("TouchGal", url),
                url=url,
                thumb_url=url,
                source="TouchGal",
                title=it.title,
                mime_hint="image",
            )
        )
    return candidates


async def _fetch_generic_scraper_image_candidates(
    asset_type: AssetType,
    query: str,
    scraper,
    source_label: str,
) -> list[AssetCandidate]:
    if asset_type not in ("cover", "spine", "hero"):
        return []
    items = await scraper.search(query, limit=8)
    candidates: list[AssetCandidate] = []
    seen_urls: set[str] = set()
    for it in items:
        raw_url = (it.background_url or it.cover_url) if asset_type == "hero" else it.cover_url
        url = _normalize_url(raw_url)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        candidates.append(
            AssetCandidate(
                id=_make_id(source_label, url),
                url=url,
                thumb_url=url,
                source=source_label,
                title=it.title,
                mime_hint="image",
            )
        )
    return candidates


# ──────────────────── Bilibili / YouTube 宣传片 PV 检索 ────────────────────


def _ytdlp_search_pv_sync(
    prefix: str,
    search_term: str,
    source_label: str,
    proxy_url: str,
    max_items: int = 6,
) -> list[AssetCandidate]:
    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "logger": _SILENT_YDL_LOGGER,
        "extract_flat": True,
        "skip_download": True,
        "socket_timeout": 8,
        "retries": 0,
        "ignoreerrors": True,
    }
    if proxy_url:
        ydl_opts["proxy"] = proxy_url

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"{prefix}:{search_term}", download=False)
    except Exception as exc:
        logger.debug("[%s] PV yt-dlp search failed for %r: %s", source_label, search_term, exc)
        return []

    if not isinstance(info, dict):
        return []

    results: list[AssetCandidate] = []
    for entry in info.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        dur = _safe_int(entry.get("duration"))
        if dur is not None and not (PV_MIN_DURATION_SEC <= dur <= PV_MAX_DURATION_SEC):
            continue

        raw_url = str(entry.get("webpage_url") or entry.get("url") or "").strip()
        if not raw_url:
            continue
        if source_label == "YouTube" and not raw_url.startswith("http"):
            raw_url = f"https://www.youtube.com/watch?v={raw_url}"
        elif source_label == "Bilibili" and not raw_url.startswith("http"):
            raw_url = f"https://www.bilibili.com/video/{raw_url}"

        title = str(entry.get("title") or "").strip()
        if not title:
            continue

        thumb = _normalize_url(entry.get("thumbnail"))
        if not thumb and isinstance(entry.get("thumbnails"), list) and entry["thumbnails"]:
            first_t = entry["thumbnails"][-1] if len(entry["thumbnails"]) > 1 else entry["thumbnails"][0]
            if isinstance(first_t, dict):
                thumb = _normalize_url(first_t.get("url"))

        results.append(
            AssetCandidate(
                id=_make_id(source_label, raw_url),
                url=raw_url,
                thumb_url=thumb,
                source=source_label,
                title=title,
                duration=dur,
                mime_hint="video_page",
            )
        )
        if len(results) >= max_items:
            break

    return results


async def _fetch_steam_pv_candidates(
    query: str,
    *,
    steam_appid: str = "",
    alt_titles: list[str] | None = None,
    proxy_url: str = "",
) -> list[AssetCandidate]:
    """优先按给定 steam_appid 拉取 Steam 官方 PV；缺失 appid 时按高可信度名称匹配兜底"""
    clean_appid = (steam_appid or "").strip()
    if not clean_appid:
        clean_appid = (
            await match_steam_appid(
                query,
                alt_titles=alt_titles,
                proxy_url=proxy_url,
            )
            or ""
        )
    if not clean_appid:
        return []

    raw_trailers = await fetch_steam_trailers(clean_appid, proxy_url=proxy_url)
    return [
        AssetCandidate(
            id=tr["id"],
            url=tr["url"],
            fallback_urls=list(tr.get("fallback_urls") or []),
            thumb_url=tr["thumb_url"],
            source="Steam",
            platform="Steam",
            is_official=True,
            title=tr["title"],
            duration=tr.get("duration"),
            mime_hint=tr.get("mime_hint") or "mp4",
        )
        for tr in raw_trailers[:8]
    ]


async def _search_bilibili_pv(
    term: str,
    proxy_url: str,
    game_titles: list[str],
) -> list[AssetCandidate]:
    raw_items = await search_bilibili_videos(
        term,
        page_size=8,
        min_duration=PV_MIN_DURATION_SEC,
        max_duration=PV_MAX_DURATION_SEC,
        proxy_url=proxy_url,
        game_titles=game_titles,
        kind="pv",
    )
    return [
        AssetCandidate(
            id=it["id"],
            url=it["url"],
            thumb_url=it["thumbnail"],
            source="Bilibili",
            platform="Bilibili",
            is_official=False,
            title=it["title"],
            duration=it["duration"] or None,
            mime_hint="video_page",
        )
        for it in raw_items[:6]
    ]


async def _fetch_bilibili_pv_candidates(
    query: str,
    alt_titles: list[str],
    proxy_url: str,
) -> list[AssetCandidate]:
    cleaned = query.strip()
    if not cleaned:
        return []
    game_titles = [t for t in [cleaned, *alt_titles] if t and t.strip()]

    merged: list[AssetCandidate] = []
    seen_urls: set[str] = set()

    for suffix in ("PV", "宣传片"):
        batch = await _search_bilibili_pv(f"{cleaned} {suffix}", proxy_url, game_titles)
        for item in batch:
            if item.url and item.url not in seen_urls:
                seen_urls.add(item.url)
                merged.append(item)
        if len(merged) >= 4:
            break

    return merged[:8]


async def _fetch_youtube_pv_candidates(
    query: str,
    proxy_url: str,
) -> list[AssetCandidate]:
    cleaned = query.strip()
    if not cleaned:
        return []

    async def _run_yt(term: str) -> list[AssetCandidate]:
        try:
            items = await asyncio.wait_for(
                asyncio.to_thread(_ytdlp_search_pv_sync, "ytsearch8", term, "YouTube", proxy_url, 6),
                timeout=PV_SEARCH_TIMEOUT_SEC,
            )
            for it in items:
                it.platform = "YouTube"
            return items
        except Exception as exc:
            logger.debug("[YouTube] PV search timeout/error for %r: %s", term, exc)
            return []

    merged: list[AssetCandidate] = []
    seen_urls: set[str] = set()
    for suffix in ("PV", "trailer"):
        batch = await _run_yt(f"{cleaned} {suffix}")
        for item in batch:
            if item.url and item.url not in seen_urls:
                seen_urls.add(item.url)
                merged.append(item)
        if len(merged) >= 4:
            break
    return merged[:6]


async def _fetch_video_pv_candidates(
    query: str,
    proxy_url: str,
    alt_titles: list[str] | None = None,
) -> list[AssetCandidate]:
    cleaned = query.strip()
    if not cleaned:
        return []
    alts = alt_titles or []

    bili_res, yt_res = await asyncio.gather(
        _fetch_bilibili_pv_candidates(cleaned, alts, proxy_url),
        _fetch_youtube_pv_candidates(cleaned, proxy_url),
        return_exceptions=True,
    )

    merged: list[AssetCandidate] = []
    seen_urls: set[str] = set()
    for batch in (bili_res, yt_res):
        if not isinstance(batch, list):
            continue
        for item in batch:
            if item.url and item.url not in seen_urls:
                seen_urls.add(item.url)
                merged.append(item)
    return merged[:8]


# ──────────────────── 统一编排入口 ────────────────────


async def search_asset_candidates(
    asset_type: AssetType,
    query: str,
    source: str = "all",
    proxy_url: str = "",
    api_keys: dict[str, Any] | None = None,
    allow_nsfw: bool = True,
    steam_appid: str = "",
    alt_title: str = "",
) -> dict[str, Any]:
    """按资产类型与指定数据源并发聚合多候选结果，单源异常静默跳过"""
    cleaned_q = (query or "").strip()
    cleaned_alt = (alt_title or "").strip()
    alt_titles = [cleaned_alt] if cleaned_alt and cleaned_alt != cleaned_q else []
    keys = api_keys or {}
    sgdb_key = str(keys.get("steamgriddb") or "").strip()
    bgm_key = str(keys.get("bangumi") or "").strip()
    tgal_key = str(keys.get("touchgal") or "").strip()

    norm_source = SOURCE_ALIASES.get((source or "all").strip().lower(), "all")

    if not cleaned_q and not (asset_type == "pv" and (steam_appid or "").strip()):
        return {
            "asset_type": asset_type,
            "query": cleaned_q,
            "source": norm_source,
            "count": 0,
            "sgdb_configured": bool(sgdb_key),
            "steam_empty": False,
            "warnings": [],
            "items": [],
        }

    # PV 专用智能编排：auto/all 模式下严格优先 Steam 官方预告片，无结果再降级其他平台
    if asset_type == "pv":
        pv_items: list[AssetCandidate] = []
        steam_empty = False

        if norm_source in ("auto", "all"):
            steam_items = await _fetch_steam_pv_candidates(
                cleaned_q,
                steam_appid=steam_appid,
                alt_titles=alt_titles,
                proxy_url=proxy_url,
            )
            if steam_items:
                pv_items = steam_items
            else:
                steam_empty = True
                pv_items = await _fetch_video_pv_candidates(cleaned_q, proxy_url, alt_titles=alt_titles)
        elif norm_source == "steam":
            pv_items = await _fetch_steam_pv_candidates(
                cleaned_q,
                steam_appid=steam_appid,
                alt_titles=alt_titles,
                proxy_url=proxy_url,
            )
            steam_empty = len(pv_items) == 0
        elif norm_source == "bilibili":
            pv_items = await _fetch_bilibili_pv_candidates(cleaned_q, alt_titles, proxy_url)
        elif norm_source == "youtube":
            pv_items = await _fetch_youtube_pv_candidates(cleaned_q, proxy_url)
        else:
            pv_items = await _fetch_video_pv_candidates(cleaned_q, proxy_url, alt_titles=alt_titles)

        return {
            "asset_type": asset_type,
            "query": cleaned_q,
            "source": norm_source,
            "count": len(pv_items),
            "sgdb_configured": bool(sgdb_key),
            "steam_empty": steam_empty,
            "warnings": [],
            "items": [it.model_dump() for it in pv_items],
        }

    sgdb = SteamGridDBScraper(proxy_url=proxy_url, api_key=sgdb_key, allow_nsfw=allow_nsfw)
    vndb = VNDBScraper(proxy_url=proxy_url, allow_nsfw=allow_nsfw)
    bgm = BangumiScraper(proxy_url=proxy_url, api_key=bgm_key, allow_nsfw=allow_nsfw)
    steam = SteamScraper(proxy_url=proxy_url, allow_nsfw=allow_nsfw)
    tgal = TouchGalScraper(proxy_url=proxy_url, api_key=tgal_key, allow_nsfw=allow_nsfw)
    ymgal = YMGalScraper(
        proxy_url=proxy_url,
        client_id=str(keys.get("ymgal_client_id") or ""),
        client_secret=str(keys.get("ymgal_client_secret") or ""),
        allow_nsfw=allow_nsfw,
    )
    kungal = KungalScraper(
        proxy_url=proxy_url,
        api_key=str(keys.get("kungal_token") or ""),
        base_url=str(keys.get("kungal_base_url") or ""),
        allow_nsfw=allow_nsfw,
    )
    dlsite = DLsiteScraper(proxy_url=proxy_url, allow_nsfw=allow_nsfw)
    igdb = IGDBScraper(
        proxy_url=proxy_url,
        client_id=str(keys.get("igdb_client_id") or ""),
        client_secret=str(keys.get("igdb_client_secret") or ""),
        allow_nsfw=allow_nsfw,
    )

    if asset_type == "logo":
        default_sources = ["steamgriddb", "steam"]
    elif asset_type == "hero":
        default_sources = ["steamgriddb", "vndb", "steam", "kungal", "igdb"]
    else:
        default_sources = ["steamgriddb", "ymgal", "vndb", "bangumi", "kungal", "dlsite", "steam"]

    target_sources = default_sources if norm_source in ("all", "auto") else [norm_source]

    warnings: list[str] = []

    async def _run_source(src_name: str) -> list[AssetCandidate]:
        if src_name == "steamgriddb":
            items, w = await _fetch_sgdb_candidates(
                asset_type, cleaned_q, sgdb, steam_appid=steam_appid
            )
            warnings.extend(w)
            return items
        if src_name == "vndb":
            return await _fetch_vndb_candidates(asset_type, cleaned_q, vndb)
        if src_name == "bangumi":
            return await _fetch_bangumi_candidates(asset_type, cleaned_q, bgm)
        if src_name == "steam":
            return await _fetch_steam_candidates(asset_type, cleaned_q, steam)
        if src_name == "ymgal":
            return await _fetch_generic_scraper_image_candidates(asset_type, cleaned_q, ymgal, "YMGal")
        if src_name == "kungal":
            return await _fetch_generic_scraper_image_candidates(asset_type, cleaned_q, kungal, "Kungal")
        if src_name == "dlsite":
            return await _fetch_generic_scraper_image_candidates(asset_type, cleaned_q, dlsite, "DLsite")
        if src_name == "igdb":
            if not igdb.is_configured():
                return []
            return await _fetch_generic_scraper_image_candidates(asset_type, cleaned_q, igdb, "IGDB")
        if src_name == "touchgal":
            return await _fetch_touchgal_candidates(asset_type, cleaned_q, tgal)
        return []

    batches = await asyncio.gather(
        *[_run_source(src) for src in target_sources],
        return_exceptions=True,
    )

    merged: list[AssetCandidate] = []
    seen_urls: set[str] = set()
    for batch in batches:
        if isinstance(batch, Exception):
            logger.debug("Asset search sub-task error: %s", batch)
            continue
        for item in batch:
            if item.url and item.url not in seen_urls:
                seen_urls.add(item.url)
                if not item.platform:
                    item.platform = item.source
                merged.append(item)

    dedup_warnings = list(dict.fromkeys(warnings))
    return {
        "asset_type": asset_type,
        "query": cleaned_q,
        "source": norm_source,
        "count": len(merged),
        "sgdb_configured": bool(sgdb_key),
        "steam_empty": False,
        "warnings": dedup_warnings,
        "items": [it.model_dump() for it in merged],
    }


# ──────────────────── PV 视频强制本地化异步下载（直链 MP4 / HLS / Bilibili / YouTube） ────────────────────


def is_direct_pv_url(url: str, mime_hint: str = "") -> bool:
    hint = (mime_hint or "").strip().lower()
    if hint in ("hls", "mp4", "webm"):
        return True
    if hint == "video_page":
        return False
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix in DIRECT_VIDEO_EXTS


async def download_pv_to_local(
    game_id: int,
    url: str,
    proxy_url: str = "",
    mime_hint: str = "",
    fallback_urls: list[str] | None = None,
) -> str:
    """委托至 media_service.download_pv_to_local（直链优先 + HLS 兼容重试 + 中文错误映射）"""
    return await _media_download_pv_to_local(
        game_id=game_id,
        url=url,
        proxy_url=proxy_url,
        mime_hint=mime_hint,
        fallback_urls=fallback_urls,
    )


async def download_pv_video(
    game_id: int,
    url: str,
    proxy_url: str = "",
    mime_hint: str = "",
    fallback_urls: list[str] | None = None,
) -> str:
    """向后兼容别名：统一委托给 download_pv_to_local"""
    return await download_pv_to_local(
        game_id=game_id,
        url=url,
        proxy_url=proxy_url,
        mime_hint=mime_hint,
        fallback_urls=fallback_urls,
    )
