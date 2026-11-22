import logging
import re
from typing import Any

from backend.scrapers.base import BaseScraper, ScrapedGameItem, clean_scraped_tags

logger = logging.getLogger("tsumugi.scrapers.vndb")

VNDB_API_URL = "https://api.vndb.org/kana/vn"
VNDB_FIELDS = (
    "id, title, alttitle, titles.lang, titles.title, titles.main, "
    "released, description, image.url, image.sexual, image.violence, "
    "developers.name, developers.original, "
    "tags.name, tags.spoiler, tags.rating, tags.category, "
    "screenshots.url, screenshots.sexual, screenshots.violence, "
    "extlinks.url, extlinks.id, extlinks.name"
)

_BBCODE_URL_RE = re.compile(r"\[url=[^\]]*\](.*?)\[/url\]", re.IGNORECASE | re.DOTALL)
_BBCODE_SPOILER_RE = re.compile(r"\[spoiler\].*?\[/spoiler\]", re.IGNORECASE | re.DOTALL)
_BBCODE_TAG_RE = re.compile(r"\[/?[a-zA-Z0-9*=_-]+\]")
_STEAM_APP_RE = re.compile(r"store\.steampowered\.com/app/(\d+)")


def _clean_vndb_bbcode(text: str | None) -> str:
    if not text:
        return ""
    cleaned = _BBCODE_SPOILER_RE.sub("", text)
    cleaned = _BBCODE_URL_RE.sub(r"\1", cleaned)
    cleaned = _BBCODE_TAG_RE.sub("", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


class VNDBScraper(BaseScraper):
    """VNDB Kana API v2 刮削器（专精 Galgame 开发商、防剧透标签与精确元数据）"""

    source_name = "VNDB"

    def _parse_vn_entry(self, entry: dict[str, Any]) -> ScrapedGameItem:
        vn_id = str(entry.get("id", ""))
        default_title = entry.get("title") or ""
        alt_title = entry.get("alttitle") or ""

        # 优先提取中文译名，同时保留日文/英文原名作为副标题
        zh_title = ""
        ja_title = alt_title
        for t in entry.get("titles") or []:
            lang = (t.get("lang") or "").lower()
            t_str = (t.get("title") or "").strip()
            if not t_str:
                continue
            if lang == "zh-hans" and not zh_title:
                zh_title = t_str
            elif lang == "zh-hant" and not zh_title:
                zh_title = t_str
            elif lang == "ja" and not ja_title:
                ja_title = t_str

        display_title = zh_title or default_title or ja_title or vn_id
        sub_candidates = [ja_title, default_title]
        sub_title = next((c for c in sub_candidates if c and c != display_title), "")

        # 开发商列表
        devs: list[str] = []
        for dev in entry.get("developers") or []:
            name = dev.get("original") or dev.get("name") or ""
            if name and name not in devs:
                devs.append(name)

        # 防剧透标签过滤：仅保留 spoiler == 0 且评分较高的标签
        raw_tags = entry.get("tags") or []
        safe_tags = [
            t for t in raw_tags
            if int(t.get("spoiler", 0)) == 0 and float(t.get("rating", 0)) >= 1.8
        ]
        safe_tags.sort(key=lambda t: float(t.get("rating", 0)), reverse=True)
        dev_str = ", ".join(devs)
        tags = clean_scraped_tags(
            [str(t["name"]) for t in safe_tags[:24] if t.get("name")],
            title=display_title,
            sub_title=sub_title,
            developer=dev_str,
        )

        # NSFW 判定与封面过滤
        image_obj = entry.get("image") or {}
        img_sexual = float(image_obj.get("sexual") or 0)
        img_violence = float(image_obj.get("violence") or 0)
        is_nsfw = img_sexual >= 1.0 or any(
            t.get("category") == "ero" and float(t.get("rating", 0)) >= 1.5
            for t in raw_tags
        )

        cover_url = ""
        if image_obj.get("url"):
            if self.allow_nsfw or (img_sexual < 1.0 and img_violence < 1.0):
                cover_url = str(image_obj["url"])

        # 截图提取与 NSFW 过滤
        screenshots: list[str] = []
        for ss in entry.get("screenshots") or []:
            ss_url = ss.get("url")
            if not ss_url:
                continue
            ss_sexual = float(ss.get("sexual") or 0)
            ss_violence = float(ss.get("violence") or 0)
            if not self.allow_nsfw and (ss_sexual >= 1.0 or ss_violence >= 1.0):
                continue
            screenshots.append(str(ss_url))
            if len(screenshots) >= 12:
                break

        # 从外链中提取 Steam AppID（供聚合引擎联动 Steam / SteamGridDB）
        extra_ids: dict[str, str] = {"vndb": vn_id}
        for link in entry.get("extlinks") or []:
            url = str(link.get("url") or "")
            m = _STEAM_APP_RE.search(url)
            if m:
                extra_ids["steam"] = m.group(1)
                break

        released = str(entry.get("released") or "")
        if released.upper() == "TBA":
            released = ""

        return ScrapedGameItem(
            source=self.source_name,
            external_id=vn_id,
            title=display_title,
            sub_title=sub_title,
            developer=", ".join(devs),
            publisher="",
            release_date=released,
            synopsis=_clean_vndb_bbcode(entry.get("description")),
            tags=tags,
            is_nsfw=is_nsfw,
            cover_url=cover_url,
            logo_url="",
            hero_bg_url=screenshots[0] if screenshots else "",
            pv_url="",
            screenshots=screenshots,
            extra_ids=extra_ids,
        )

    async def search(self, keyword: str, limit: int = 8) -> list[ScrapedGameItem]:
        query = keyword.strip()
        if not query:
            return []

        payload = {
            "filters": ["search", "=", query],
            "fields": VNDB_FIELDS,
            "sort": "searchrank",
            "results": max(1, min(limit, 25)),
        }
        try:
            async with self._build_client() as client:
                resp = await client.post(VNDB_API_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("VNDB search failed for %r: %s", query, exc)
            return []

        results = data.get("results") or []
        return [self._parse_vn_entry(item) for item in results]

    async def get_detail(self, external_id: str) -> ScrapedGameItem | None:
        vn_id = external_id.strip()
        if not vn_id:
            return None
        if not vn_id.startswith("v"):
            vn_id = f"v{vn_id}"

        payload = {
            "filters": ["id", "=", vn_id],
            "fields": VNDB_FIELDS,
            "results": 1,
        }
        try:
            async with self._build_client() as client:
                resp = await client.post(VNDB_API_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("VNDB get_detail failed for %r: %s", vn_id, exc)
            return None

        results = data.get("results") or []
        if not results:
            return None
        return self._parse_vn_entry(results[0])
