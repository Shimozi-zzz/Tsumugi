import logging
from typing import Any
from urllib.parse import quote

from backend.scrapers.base import BaseScraper, ScrapedGameItem, clean_scraped_tags

logger = logging.getLogger("tsumugi.scrapers.bangumi")

BGM_BASE_URL = "https://api.bgm.tv"
BANGUMI_USER_AGENT = "Shimozi/Tsumugi (https://github.com/tsumugi-platform)"


def _extract_infobox_value(infobox: list[dict[str, Any]] | None, target_keys: set[str]) -> str:
    if not infobox:
        return ""
    for entry in infobox:
        key = str(entry.get("key") or "").strip()
        if key in target_keys:
            val = entry.get("value")
            if isinstance(val, str):
                return val.strip()
            if isinstance(val, list):
                parts = []
                for item in val:
                    if isinstance(item, dict) and item.get("v"):
                        parts.append(str(item["v"]).strip())
                    elif isinstance(item, str):
                        parts.append(item.strip())
                return ", ".join(p for p in parts if p)
    return ""


class BangumiScraper(BaseScraper):
    """Bangumi API v0 刮削器（专精中文标题、简介、发行信息与二次元社区标签）"""

    source_name = "BGM"

    def _auth_headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": BANGUMI_USER_AGENT,
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _parse_subject(self, item: dict[str, Any]) -> ScrapedGameItem:
        bgm_id = str(item.get("id", ""))
        name_cn = (item.get("name_cn") or "").strip()
        name_orig = (item.get("name") or "").strip()

        title = name_cn or name_orig or bgm_id
        sub_title = name_orig if (name_cn and name_orig and name_orig != name_cn) else ""

        infobox = item.get("infobox") or []
        developer = _extract_infobox_value(infobox, {"开发", "开发商", "制作", "游戏开发", "研发"})
        publisher = _extract_infobox_value(infobox, {"发行", "发行商", "代理", "出品"})
        release_date = (
            str(item.get("date") or "").strip()
            or _extract_infobox_value(infobox, {"发行日期", "发售日期", "发售日", "上市日期"})
        )

        # 提取社区高票标签并去脏清洗
        raw_tags = item.get("tags") or []
        if raw_tags and isinstance(raw_tags[0], dict):
            sorted_tags = sorted(raw_tags, key=lambda t: int(t.get("count", 0)), reverse=True)
            candidate_tags = [str(t["name"]) for t in sorted_tags[:24] if t.get("name")]
        else:
            candidate_tags = [str(t) for t in (item.get("meta_tags") or [])[:24]]
        tags = clean_scraped_tags(
            candidate_tags,
            title=title,
            sub_title=sub_title,
            developer=developer,
            publisher=publisher,
        )

        images = item.get("images") or {}
        cover_url = (
            images.get("large")
            or images.get("common")
            or images.get("medium")
            or images.get("grid")
            or ""
        )

        is_nsfw = bool(item.get("nsfw", False))
        if not is_nsfw:
            nsfw_markers = {"R18", "18禁", "拔作", "黄油", "成人"}
            is_nsfw = any(t in nsfw_markers for t in tags)

        return ScrapedGameItem(
            source=self.source_name,
            external_id=bgm_id,
            title=title,
            sub_title=sub_title,
            developer=developer,
            publisher=publisher,
            release_date=release_date,
            synopsis=(item.get("summary") or "").strip(),
            tags=tags,
            is_nsfw=is_nsfw,
            cover_url=str(cover_url),
            logo_url="",
            hero_bg_url="",
            pv_url="",
            screenshots=[],
            extra_ids={"bgm": bgm_id},
            bangumi_id=bgm_id,
        )

    async def search(self, keyword: str, limit: int = 8) -> list[ScrapedGameItem]:
        query = keyword.strip()
        if not query:
            return []

        capped = max(1, min(limit, 20))
        headers = self._auth_headers()

        # 优先使用 Bangumi API v0 现代搜索端点（type=4 表示游戏）
        payload: dict[str, Any] = {
            "keyword": query,
            "sort": "match",
            "filter": {
                "type": [4],
                "nsfw": True if self.allow_nsfw else False,
            },
        }
        try:
            async with self._build_client(headers=headers) as client:
                resp = await client.post(
                    f"{BGM_BASE_URL}/v0/search/subjects",
                    params={"limit": capped, "offset": 0},
                    json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("data") or []
                    return [self._parse_subject(it) for it in items]

                # 降级到旧版开放搜索接口（无需 Token 即可搜索常规条目）
                fallback_resp = await client.get(
                    f"{BGM_BASE_URL}/search/subject/{quote(query)}",
                    params={"type": 4, "responseGroup": "large", "max_results": capped},
                )
                fallback_resp.raise_for_status()
                fb_data = fallback_resp.json()
                fb_list = fb_data.get("list") or []
                return [self._parse_subject(it) for it in fb_list]
        except Exception as exc:
            logger.warning("Bangumi search failed for %r: %s", query, exc)
            return []

    async def get_detail(self, external_id: str) -> ScrapedGameItem | None:
        bgm_id = external_id.strip()
        if not bgm_id:
            return None
        try:
            async with self._build_client(headers=self._auth_headers()) as client:
                resp = await client.get(f"{BGM_BASE_URL}/v0/subjects/{bgm_id}")
                resp.raise_for_status()
                data = resp.json()
                return self._parse_subject(data)
        except Exception as exc:
            logger.warning("Bangumi get_detail failed for %r: %s", bgm_id, exc)
            return None
