import html
import logging
import re
from typing import Any

from backend.scrapers.base import BaseScraper, ScrapedGameItem, clean_scraped_tags

logger = logging.getLogger("tsumugi.scrapers.steam")

STEAM_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
STEAM_DETAIL_URL = "https://store.steampowered.com/api/appdetails"
STEAM_CDN_BASE = "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps"

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_CN_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


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
        """优先提取 Steam 直链 MP4（mp4.max / mp4.480），缺失时回退 HLS (.m3u8) 或 WebM"""
        if not movies:
            return ""
        for movie in movies:
            mp4 = movie.get("mp4") or {}
            if mp4.get("max"):
                return str(mp4["max"])
            if mp4.get("480"):
                return str(mp4["480"])
            hls = movie.get("hls_h264")
            if hls:
                return str(hls)
            webm = movie.get("webm") or {}
            if webm.get("max"):
                return str(webm["max"])
            if webm.get("480"):
                return str(webm["480"])
        return ""

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
