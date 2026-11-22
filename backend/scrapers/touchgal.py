import json
import logging
import re
from typing import Any

from backend.scrapers.base import BaseScraper, ScrapedGameItem, clean_scraped_tags

logger = logging.getLogger("tsumugi.scrapers.touchgal")

TOUCHGAL_ENDPOINTS = (
    "https://www.touchgal.io",
    "https://www.touchgal.top",
)

_HTML_RE = re.compile(r"<[^>]+>")


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s{3,}", "\n\n", _HTML_RE.sub("", value)).strip()


class TouchGalScraper(BaseScraper):
    """TouchGal 刮削器（专精中文 Galgame 译名、汉化简介与宽幅横版封面）"""

    source_name = "TGAL"

    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": "TsumugiGameLibrary/0.3 (https://github.com/tsumugi-local)",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _parse_entry(self, entry: dict[str, Any]) -> ScrapedGameItem:
        tg_id = str(entry.get("uniqueId") or entry.get("id") or "")
        title = str(entry.get("name") or entry.get("title") or tg_id).strip()
        sub_title = str(entry.get("originalName") or entry.get("subTitle") or "").strip()
        if sub_title == title:
            sub_title = ""

        banner = str(entry.get("banner") or entry.get("cover") or entry.get("image") or "")
        tags_raw = entry.get("tags") or []
        tags: list[str] = []
        for t in tags_raw:
            if isinstance(t, dict) and t.get("name"):
                tags.append(str(t["name"]))
            elif isinstance(t, str) and t.strip():
                tags.append(t.strip())

        is_nsfw = bool(entry.get("nsfw", entry.get("isNsfw", True)))
        synopsis = _clean_text(
            entry.get("introduction")
            or entry.get("description")
            or entry.get("summary")
            or ""
        )

        developer = str(entry.get("developer") or entry.get("brand") or "").strip()
        publisher = str(entry.get("publisher") or "").strip()
        cleaned_tags = clean_scraped_tags(
            tags,
            title=title,
            sub_title=sub_title,
            developer=developer,
            publisher=publisher,
        )

        # TouchGal 通常提供 16:9 横幅图，既可作为 Hero 也可作兜底封面
        return ScrapedGameItem(
            source=self.source_name,
            external_id=tg_id,
            title=title,
            sub_title=sub_title,
            developer=developer,
            publisher=publisher,
            release_date=str(entry.get("releaseDate") or entry.get("publishDate") or "").strip(),
            synopsis=synopsis,
            tags=cleaned_tags,
            is_nsfw=is_nsfw,
            cover_url=banner if (self.allow_nsfw or not is_nsfw) else "",
            logo_url="",
            hero_bg_url=banner if (self.allow_nsfw or not is_nsfw) else "",
            pv_url="",
            screenshots=[],
            extra_ids={"tgal": tg_id},
        )

    async def search(self, keyword: str, limit: int = 8) -> list[ScrapedGameItem]:
        query = keyword.strip()
        if not query:
            return []

        payload = {
            "queryString": json.dumps([{"type": "keyword", "name": query}], ensure_ascii=False),
            "limit": max(1, min(limit, 20)),
            "page": 1,
            "searchOption": {
                "searchInIntroduction": False,
                "searchInAlias": True,
                "searchInTag": False,
            },
            "selectedType": "all",
            "selectedLanguage": "all",
            "selectedPlatform": "all",
            "sortField": "resource_update_time",
            "sortOrder": "desc",
            "selectedYears": ["all"],
            "selectedMonths": ["all"],
        }

        async with self._build_client(headers=self._headers(), timeout=10.0) as client:
            for base_url in TOUCHGAL_ENDPOINTS:
                try:
                    resp = await client.post(f"{base_url}/api/search", json=payload)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    raw_list = (
                        data.get("galgames")
                        or data.get("data")
                        or data.get("results")
                        or (data if isinstance(data, list) else [])
                    )
                    if isinstance(raw_list, list) and raw_list:
                        items = [self._parse_entry(item) for item in raw_list[:limit] if isinstance(item, dict)]
                        if not self.allow_nsfw:
                            items = [it for it in items if not it.is_nsfw]
                        return items
                except Exception as exc:
                    logger.debug("TouchGal search failed on %s: %s", base_url, exc)
                    continue
        return []

    async def get_detail(self, external_id: str) -> ScrapedGameItem | None:
        tg_id = external_id.strip()
        if not tg_id:
            return None

        async with self._build_client(headers=self._headers(), timeout=10.0) as client:
            for base_url in TOUCHGAL_ENDPOINTS:
                for path in (f"/api/galgame/{tg_id}", f"/api/patch/{tg_id}"):
                    try:
                        resp = await client.get(f"{base_url}{path}")
                        if resp.status_code != 200:
                            continue
                        data = resp.json()
                        entry = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
                        if isinstance(entry, dict) and (entry.get("name") or entry.get("title")):
                            return self._parse_entry(entry)
                    except Exception as exc:
                        logger.debug("TouchGal detail failed on %s%s: %s", base_url, path, exc)
        return None
