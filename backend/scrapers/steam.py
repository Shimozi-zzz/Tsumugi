import hashlib
import html
import logging
import re
from typing import Any

import httpx

from backend.scrapers.base import BaseScraper, ScrapedGameItem, clean_scraped_tags

logger = logging.getLogger("tsumugi.scrapers.steam")

STEAM_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
STEAM_DETAIL_URL = "https://store.steampowered.com/api/appdetails"
STEAM_CDN_BASE = "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps"

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
        # 完整包含且长度覆盖率足够高（防止短词误撞长副标题或合集）
        shorter, longer = (q_norm, cand_norm) if len(q_norm) <= len(cand_norm) else (cand_norm, q_norm)
        if len(shorter) >= 2 and shorter in longer:
            ratio = len(shorter) / max(len(longer), 1)
            if ratio >= 0.55:
                best = max(best, 0.72 + 0.25 * ratio)
                continue
        # 2-gram Jaccard 相似度兜底（处理轻微标点/罗马字/译名差异）
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

        mp4_url = _norm_media_url(mp4_obj.get("max") or mp4_obj.get("480"))
        hls_url = _norm_media_url(movie.get("hls_h264"))
        webm_url = _norm_media_url(webm_obj.get("max") or webm_obj.get("480"))
        dash_url = _norm_media_url(movie.get("dash_h264"))

        if mp4_url:
            play_url, mime_hint = mp4_url, "mp4"
        elif hls_url:
            play_url, mime_hint = hls_url, "hls"
        elif webm_url:
            play_url, mime_hint = webm_url, "webm"
        elif dash_url:
            play_url, mime_hint = dash_url, "dash"
        else:
            continue

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
    """Steam Store API 刮削器（支持中文商店元数据、官方竖版封面/Hero、截图与 .m3u8 / .mp4 PV 提取）"""

    source_name = "STEAM"

    async def _check_url_exists(self, client, url: str) -> bool:
        try:
            resp = await client.head(url, timeout=6.0)
            return resp.status_code == 200
        except Exception:
            return False

    def _extract_pv_url(self, movies: list[dict[str, Any]] | None) -> str:
        """优先提取 Steam 直链 MP4（mp4.max / mp4.480），缺失时回退 HLS / WebM / DASH"""
        parsed = parse_steam_movies(movies)
        return parsed[0]["url"] if parsed else ""

    async def search(self, keyword: str, limit: int = 8) -> list[ScrapedGameItem]:
        query = keyword.strip()
        if not query:
            return []

        try:
            async with self._build_client() as client:
                resp = await client.get(
                    STEAM_SEARCH_URL,
                    params={"term": query, "l": "schinese", "cc": "CN"},
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items") or []
                if not items:
                    resp = await client.get(
                        STEAM_SEARCH_URL,
                        params={"term": query, "l": "schinese", "cc": "US"},
                    )
                    resp.raise_for_status()
                    items = resp.json().get("items") or []
        except Exception as exc:
            logger.warning("Steam search failed for %r: %s", query, exc)
            return []

        results: list[ScrapedGameItem] = []
        for entry in items[:limit]:
            appid = str(entry.get("id", ""))
            if not appid:
                continue
            vertical_cover = f"{STEAM_CDN_BASE}/{appid}/library_600x900_2x.jpg"
            hero_bg = f"{STEAM_CDN_BASE}/{appid}/library_hero.jpg"
            logo_url = f"{STEAM_CDN_BASE}/{appid}/logo.png"
            results.append(
                ScrapedGameItem(
                    source=self.source_name,
                    external_id=appid,
                    title=str(entry.get("name") or appid),
                    sub_title="",
                    developer="",
                    publisher="",
                    release_date="",
                    synopsis="",
                    tags=[],
                    is_nsfw=False,
                    cover_url=vertical_cover or str(entry.get("tiny_image") or ""),
                    logo_url=logo_url,
                    hero_bg_url=hero_bg,
                    pv_url="",
                    screenshots=[],
                    extra_ids={"steam": appid},
                )
            )
        return results

    async def get_detail(self, external_id: str) -> ScrapedGameItem | None:
        appid = external_id.strip()
        if not appid:
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

                # 检查高质量竖版封面 / Hero / Logo 是否真实存在，不存在时优雅回退
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
        dev_str = ", ".join(info.get("developers") or [])
        pub_str = ", ".join(info.get("publishers") or [])
        cleaned_tags = clean_scraped_tags(
            tags,
            title=title_str,
            developer=dev_str,
            publisher=pub_str,
        )

        return ScrapedGameItem(
            source=self.source_name,
            external_id=appid,
            title=title_str,
            sub_title="",
            developer=dev_str,
            publisher=pub_str,
            release_date=_normalize_date((info.get("release_date") or {}).get("date")),
            synopsis=synopsis,
            tags=cleaned_tags,
            is_nsfw=is_nsfw,
            cover_url=str(cover_url),
            logo_url=str(logo_url),
            hero_bg_url=str(hero_bg_url),
            pv_url=pv_url,
            screenshots=screenshots,
            extra_ids={"steam": appid},
        )
