from __future__ import annotations

import hashlib
import html
import logging
import re
import time
from typing import Any

import httpx

from backend.scrapers.base import (
    BaseScraper,
    ScraperGameDetail,
    ScraperSearchResult,
    clean_scraped_tags,
    normalize_external_ids,
    split_entity_names,
)

logger = logging.getLogger("tsumugi.scrapers.steam")

STEAM_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
STEAM_DETAIL_URL = "https://store.steampowered.com/api/appdetails"
STEAM_CDN_BASE = "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps"

_STEAM_URL_RE = re.compile(
    r"https?://(?:store\.steampowered\.com|steamcommunity\.com)/app/(\d+)",
    re.IGNORECASE,
)
_STEAM_URI_RE = re.compile(r"^steam://(?:run|rungameid|store)/(\d+)", re.IGNORECASE)
_STEAM_PREFIX_RE = re.compile(r"^steam[:/#\s-]?(?:app/)?(\d+)$", re.IGNORECASE)
_PURE_APPID_RE = re.compile(r"^(\d{3,9})$")

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_CN_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_NORM_STRIP_RE = re.compile(r"[\s\-_~～·•:：,，.。!！?？'\"「」『』【】()（）\[\]/\\]+")
_EDITION_NOISE_RE = re.compile(
    r"\b(hd|remastered|definitive|complete|ultimate|deluxe|edition|version|ver|pc|steam)\b",
    re.IGNORECASE,
)


def _normalize_steam_title(raw: str) -> str:
    text = (raw or "").strip().lower()
    if not text:
        return ""
    text = _EDITION_NOISE_RE.sub("", text)
    return _NORM_STRIP_RE.sub("", text)


def _title_match_score(query_titles: list[str], candidate_name: str) -> float:
    """计算 Steam 搜索候选名与目标作品名集合的严格匹配分数（0~1），防同名异作错配"""
    cand_norm = _normalize_steam_title(candidate_name)
    if not cand_norm:
        return 0.0

    best = 0.0
    for q in query_titles:
        q_norm = _normalize_steam_title(q)
        if not q_norm:
            continue
        if q_norm == cand_norm:
            return 1.0
        shorter, longer = (q_norm, cand_norm) if len(q_norm) <= len(cand_norm) else (cand_norm, q_norm)
        if len(shorter) >= 2 and shorter in longer:
            ratio = len(shorter) / max(len(longer), 1)
            if ratio >= 0.55:
                best = max(best, 0.72 + 0.25 * ratio)
                continue
        if len(q_norm) >= 3 and len(cand_norm) >= 3:
            g1 = {q_norm[i : i + 2] for i in range(len(q_norm) - 1)}
            g2 = {cand_norm[i : i + 2] for i in range(len(cand_norm) - 1)}
            union = g1 | g2
            if union:
                sim = len(g1 & g2) / len(union)
                if sim >= 0.55:
                    best = max(best, sim * 0.85)
    return best


def _norm_media_url(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if s.startswith("//"):
        return f"https:{s}"
    if s.lower().startswith("http://"):
        return f"https://{s[7:]}"
    return s


def parse_steam_movies(
    movies: list[dict[str, Any]] | None,
    *,
    app_name: str = "",
    appid: str = "",
) -> list[dict[str, Any]]:
    """
    解析 Steam appdetails 中的 movies 数组，兼容 mp4 / webm / hls_h264 / dash_h264。
    返回标准化官方 PV 候选列表（按清晰度与直链友好度优先排序）。
    """
    if not movies or not isinstance(movies, list):
        return []

    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for movie in movies:
        if not isinstance(movie, dict):
            continue
        mp4_obj = movie.get("mp4") if isinstance(movie.get("mp4"), dict) else {}
        webm_obj = movie.get("webm") if isinstance(movie.get("webm"), dict) else {}

        # 严格优先提取直链视频：mp4.max > mp4.480 > webm.max > webm.480 > hls_h264 > dash_h264
        ordered_candidates: list[tuple[str, str]] = []
        for raw_u, hint in (
            (mp4_obj.get("max"), "mp4"),
            (mp4_obj.get("480"), "mp4"),
            (webm_obj.get("max"), "webm"),
            (webm_obj.get("480"), "webm"),
            (movie.get("hls_h264"), "hls"),
            (movie.get("dash_h264"), "dash"),
        ):
            norm_u = _norm_media_url(raw_u)
            if norm_u and all(existing_u != norm_u for existing_u, _ in ordered_candidates):
                ordered_candidates.append((norm_u, hint))

        if not ordered_candidates:
            continue

        play_url, mime_hint = ordered_candidates[0]
        fallback_urls = [u for u, _ in ordered_candidates[1:]]

        if play_url in seen_urls:
            continue
        seen_urls.add(play_url)

        movie_title = str(movie.get("name") or app_name or "官方宣传片").strip()
        thumb_url = _norm_media_url(movie.get("thumbnail"))
        digest = hashlib.sha1(f"Steam:{play_url}".encode("utf-8")).hexdigest()[:12]

        results.append(
            {
                "id": f"steam-{digest}",
                "url": play_url,
                "fallback_urls": fallback_urls,
                "thumb_url": thumb_url,
                "source": "Steam",
                "platform": "Steam",
                "is_official": True,
                "title": movie_title,
                "duration": None,
                "mime_hint": mime_hint,
                "appid": appid,
            }
        )

    return results


async def fetch_steam_trailers(
    appid: str,
    *,
    proxy_url: str = "",
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """按 Steam AppID 拉取官方宣传片 PV 列表（优先中文区，无数据时回退 US 区）"""
    clean_id = str(appid or "").strip()
    if not clean_id or not clean_id.isdigit():
        return []

    async def _run(http_client: httpx.AsyncClient) -> list[dict[str, Any]]:
        for cc in ("CN", "US"):
            resp = await http_client.get(
                STEAM_DETAIL_URL,
                params={"appids": clean_id, "l": "schinese", "cc": cc},
            )
            resp.raise_for_status()
            payload = resp.json()
            block = payload.get(clean_id) if isinstance(payload, dict) else None
            if isinstance(block, dict) and block.get("success") and isinstance(block.get("data"), dict):
                info = block["data"]
                trailers = parse_steam_movies(
                    info.get("movies"),
                    app_name=str(info.get("name") or "").strip(),
                    appid=clean_id,
                )
                if trailers:
                    return trailers
        return []

    try:
        if client is not None:
            return await _run(client)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(12.0),
            follow_redirects=True,
            proxy=(proxy_url.strip() or None),
        ) as owned:
            return await _run(owned)
    except Exception as exc:
        logger.debug("fetch_steam_trailers failed for appid=%s: %s", clean_id, exc)
        return []


async def match_steam_appid(
    query: str,
    *,
    alt_titles: list[str] | None = None,
    proxy_url: str = "",
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """按游戏名（优先原名/英文名/中文名）通过 Steam 商店搜索匹配高可信度 AppID，避免错配"""
    candidates_q: list[str] = []
    for raw in [*(alt_titles or []), query]:
        s = str(raw or "").strip()
        if s and s not in candidates_q:
            candidates_q.append(s)
    if not candidates_q:
        return None

    async def _search_best(http_client: httpx.AsyncClient) -> str | None:
        best_appid: str | None = None
        best_score = 0.0

        for term in candidates_q[:3]:
            items: list[dict[str, Any]] = []
            for cc in ("CN", "US"):
                try:
                    resp = await http_client.get(
                        STEAM_SEARCH_URL,
                        params={"term": term, "l": "schinese", "cc": cc},
                    )
                    resp.raise_for_status()
                    items = resp.json().get("items") or []
                    if items:
                        break
                except Exception:
                    continue

            for entry in items[:6]:
                if not isinstance(entry, dict):
                    continue
                aid = str(entry.get("id") or "").strip()
                name = str(entry.get("name") or "").strip()
                if not aid or not name:
                    continue
                score = _title_match_score(candidates_q, name)
                if score > best_score:
                    best_score = score
                    best_appid = aid
                if best_score >= 0.99:
                    return best_appid

        return best_appid if best_score >= 0.65 else None

    try:
        if client is not None:
            return await _search_best(client)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(12.0),
            follow_redirects=True,
            proxy=(proxy_url.strip() or None),
        ) as owned:
            return await _search_best(owned)
    except Exception as exc:
        logger.debug("match_steam_appid failed for %r: %s", candidates_q, exc)
        return None


def _strip_html(raw: str | None) -> str:
    if not raw:
        return ""
    text = raw.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = text.replace("</p>", "\n\n")
    text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _normalize_date(raw: str | None) -> str:
    if not raw:
        return ""
    text = raw.strip()
    m = _CN_DATE_RE.search(text)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return text


class SteamScraper(BaseScraper):
    """Steam Store API 刮削器（支持中文商店元数据、链接/纯数字 AppID 直查与官方 PV 提取）"""

    source_id = "steam"
    source_name = "STEAM"
    display_name = "Steam"
    requires_api_key = False
    categories = ("general",)
    default_timeout = 8.0

    def parse_direct_id(self, query: str) -> str | None:
        raw = (query or "").strip()
        if not raw:
            return None
        for pattern in (_STEAM_URL_RE, _STEAM_URI_RE, _STEAM_PREFIX_RE, _PURE_APPID_RE):
            m = pattern.search(raw) if pattern is _STEAM_URL_RE else pattern.match(raw)
            if m:
                return m.group(1)
        return None

    async def _check_url_exists(self, client, url: str) -> bool:
        try:
            resp = await client.head(url, timeout=4.0)
            return resp.status_code == 200
        except Exception:
            return False

    def _extract_pv_url(self, movies: list[dict[str, Any]] | None) -> str:
        parsed = parse_steam_movies(movies)
        return parsed[0]["url"] if parsed else ""

    async def search(self, query: str, limit: int = 8) -> list[ScraperSearchResult]:
        q = (query or "").strip()
        if not q:
            return []

        # 显式 URL / steam:// / steam:12345 直接详情定位；纯数字 AppID 尝试直查并在失败时回退关键词检索
        direct_id = self.parse_direct_id(q)
        if direct_id:
            detail = await self.get_detail(direct_id)
            if detail:
                return [detail]
            if not _PURE_APPID_RE.match(q):
                return []

        try:
            async with self._build_client() as client:
                resp = await client.get(
                    STEAM_SEARCH_URL,
                    params={"term": q, "l": "schinese", "cc": "CN"},
                )
                resp.raise_for_status()
                items = resp.json().get("items") or []
                if not items:
                    resp = await client.get(
                        STEAM_SEARCH_URL,
                        params={"term": q, "l": "schinese", "cc": "US"},
                    )
                    resp.raise_for_status()
                    items = resp.json().get("items") or []
        except Exception as exc:
            logger.warning("Steam search failed for %r: %s", q, exc)
            return []

        results: list[ScraperSearchResult] = []
        for entry in items[:limit]:
            if not isinstance(entry, dict):
                continue
            appid = str(entry.get("id") or "").strip()
            if not appid:
                continue
            vertical_cover = f"{STEAM_CDN_BASE}/{appid}/library_600x900_2x.jpg"
            hero_bg = f"{STEAM_CDN_BASE}/{appid}/library_hero.jpg"
            logo_url = f"{STEAM_CDN_BASE}/{appid}/logo.png"
            results.append(
                ScraperSearchResult(
                    source=self.source_id,
                    source_id=appid,
                    source_url=f"https://store.steampowered.com/app/{appid}",
                    title=str(entry.get("name") or appid),
                    original_title="",
                    cover_url=vertical_cover or str(entry.get("tiny_image") or ""),
                    background_url=hero_bg,
                    logo_url=logo_url,
                    external_ids=normalize_external_ids({"steam": appid}),
                )
            )
        return results

    async def get_detail(self, source_id: str) -> ScraperGameDetail | None:
        raw = (source_id or "").strip()
        appid = self.parse_direct_id(raw) or raw
        if not appid or not appid.isdigit():
            return None

        try:
            async with self._build_client() as client:
                resp = await client.get(
                    STEAM_DETAIL_URL,
                    params={"appids": appid, "l": "schinese", "cc": "CN"},
                )
                resp.raise_for_status()
                payload = resp.json()
                app_block = payload.get(appid) or {}
                if not app_block.get("success"):
                    resp = await client.get(
                        STEAM_DETAIL_URL,
                        params={"appids": appid, "l": "schinese", "cc": "US"},
                    )
                    resp.raise_for_status()
                    app_block = resp.json().get(appid) or {}
                if not app_block.get("success"):
                    return None
                info = app_block.get("data") or {}

                vertical_2x = f"{STEAM_CDN_BASE}/{appid}/library_600x900_2x.jpg"
                vertical_1x = f"{STEAM_CDN_BASE}/{appid}/library_600x900.jpg"
                hero_candidate = f"{STEAM_CDN_BASE}/{appid}/library_hero.jpg"
                logo_candidate = f"{STEAM_CDN_BASE}/{appid}/logo.png"

                cover_url = info.get("header_image") or ""
                if await self._check_url_exists(client, vertical_2x):
                    cover_url = vertical_2x
                elif await self._check_url_exists(client, vertical_1x):
                    cover_url = vertical_1x

                hero_bg_url = (
                    hero_candidate
                    if await self._check_url_exists(client, hero_candidate)
                    else (info.get("background_raw") or info.get("background") or "")
                )
                logo_url = (
                    logo_candidate
                    if await self._check_url_exists(client, logo_candidate)
                    else ""
                )
        except Exception as exc:
            logger.warning("Steam get_detail failed for %r: %s", appid, exc)
            return None

        descriptors = (info.get("content_descriptors") or {}).get("ids") or []
        is_nsfw = any(int(d) in (3, 4) for d in descriptors)

        tags: list[str] = []
        for g in info.get("genres") or []:
            desc = str(g.get("description") or "").strip()
            if desc and desc not in tags:
                tags.append(desc)
        for c in (info.get("categories") or [])[:5]:
            desc = str(c.get("description") or "").strip()
            if desc and desc not in tags:
                tags.append(desc)

        screenshots = [
            str(s.get("path_full") or s.get("path_thumbnail"))
            for s in (info.get("screenshots") or [])[:12]
            if s.get("path_full") or s.get("path_thumbnail")
        ]

        synopsis = _strip_html(info.get("short_description")) or _strip_html(
            info.get("about_the_game")
        )
        pv_url = self._extract_pv_url(info.get("movies"))

        title_str = str(info.get("name") or appid)
        developers = split_entity_names(info.get("developers") or [])
        publishers = split_entity_names(info.get("publishers") or [])
        cleaned_tags = clean_scraped_tags(
            tags,
            title=title_str,
            developer=", ".join(developers),
            publisher=", ".join(publishers),
        )

        rating: float | None = None
        mc = info.get("metacritic")
        if isinstance(mc, dict) and mc.get("score"):
            try:
                rating = round(float(mc["score"]) / 10.0, 2)
            except (TypeError, ValueError):
                pass

        return ScraperGameDetail(
            source=self.source_id,
            source_id=appid,
            source_url=f"https://store.steampowered.com/app/{appid}",
            title=title_str,
            original_title="",
            developers=developers,
            publishers=publishers,
            release_date=_normalize_date((info.get("release_date") or {}).get("date")),
            description=synopsis,
            tags=cleaned_tags,
            is_nsfw=is_nsfw,
            rating=rating,
            cover_url=str(cover_url),
            logo_url=str(logo_url),
            background_url=str(hero_bg_url),
            pv_url=pv_url,
            screenshots=screenshots,
            external_ids=normalize_external_ids({"steam": appid}),
        )

    async def test_connection(self, timeout: float = 6.0) -> dict[str, Any]:
        t0 = time.monotonic()
        try:
            async with self._build_client(timeout=timeout) as client:
                resp = await client.get(
                    STEAM_SEARCH_URL,
                    params={"term": "Portal", "l": "schinese", "cc": "US"},
                )
                elapsed = int((time.monotonic() - t0) * 1000)
                if resp.status_code == 429:
                    return {
                        "ok": False,
                        "source": self.source_id,
                        "latency_ms": elapsed,
                        "detail": "请求过于频繁，触发限流 (HTTP 429)",
                    }
                if resp.status_code != 200:
                    return {
                        "ok": False,
                        "source": self.source_id,
                        "latency_ms": elapsed,
                        "detail": f"接口返回异常 (HTTP {resp.status_code})",
                    }
                data = resp.json()
                items = data.get("items") if isinstance(data, dict) else []
                return {
                    "ok": True,
                    "source": self.source_id,
                    "latency_ms": elapsed,
                    "sample_count": len(items) if isinstance(items, list) else 0,
                    "detail": f"连接正常 ({elapsed}ms)",
                }
        except httpx.TimeoutException:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {
                "ok": False,
                "source": self.source_id,
                "latency_ms": elapsed,
                "detail": f"连接超时 (>{timeout:.0f}s)",
            }
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {
                "ok": False,
                "source": self.source_id,
                "latency_ms": elapsed,
                "detail": f"连接失败: {exc}",
            }
