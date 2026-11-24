from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.parse import quote

import httpx

from backend.core.scraper_settings import sanitize_touchgal_token
from backend.scrapers.base import (
    BaseScraper,
    ScraperGameDetail,
    ScraperSearchResult,
    clean_scraped_tags,
    normalize_external_ids,
    split_entity_names,
)

logger = logging.getLogger("tsumugi.scrapers.touchgal")

TOUCHGAL_API_BASE = "https://developer.touchgal.com/api/v1"
TOUCHGAL_TEST_KEYWORD = "summer"

_HTML_RE = re.compile(r"<[^>]+>")
_TGAL_URL_RE = re.compile(
    r"https?://(?:www\.|developer\.)?touchgal\.(?:com|io|top|us)/(?:games/|galgame/|patch/)?([a-zA-Z0-9_-]{4,})",
    re.IGNORECASE,
)
_TGAL_PREFIX_RE = re.compile(
    r"^(?:touchgal|tgal)[:/#\s-]+([a-zA-Z0-9_-]{3,})$",
    re.IGNORECASE,
)
_TGAL_RESERVED_SLUGS = frozenset(
    {"search", "login", "register", "about", "api", "home", "games", "galgame", "patch", "docs"}
)


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s{3,}", "\n\n", _HTML_RE.sub("", value)).strip()


def _extract_entity_names(raw: Any) -> list[str]:
    if isinstance(raw, list):
        names: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                val = str(item.get("name") or "").strip()
                if val:
                    names.extend(split_entity_names(val))
            elif isinstance(item, str) and item.strip():
                names.extend(split_entity_names(item.strip()))
        return list(dict.fromkeys(names))
    if isinstance(raw, str):
        return split_entity_names(raw.strip())
    return []


class TouchGalScraper(BaseScraper):
    """TouchGal 官方开发者 API v1 刮削器（https://developer.touchgal.com/api/v1）"""

    source_id = "touchgal"
    source_name = "TGAL"
    display_name = "TouchGal"
    requires_api_key = True
    categories = ("galgame",)
    default_timeout = 8.0

    def __init__(
        self,
        proxy_url: str = "",
        api_key: str = "",
        allow_nsfw: bool = True,
        timeout: float | None = None,
    ) -> None:
        super().__init__(
            proxy_url=proxy_url,
            api_key=sanitize_touchgal_token(api_key),
            allow_nsfw=allow_nsfw,
            timeout=timeout,
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": "TsumugiGameLibrary/0.9 (https://github.com/Shimozi-zzz/Tsumugi)",
            "Accept": "application/json",
        }
        token = sanitize_touchgal_token(self.api_key)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def parse_direct_id(self, query: str) -> str | None:
        raw = (query or "").strip()
        if not raw:
            return None
        m = _TGAL_URL_RE.search(raw)
        if m:
            slug = m.group(1).strip()
            if slug.lower() not in _TGAL_RESERVED_SLUGS:
                return slug
        m2 = _TGAL_PREFIX_RE.match(raw)
        if m2:
            slug = m2.group(1).strip()
            if slug.lower() not in _TGAL_RESERVED_SLUGS:
                return slug
        return None

    def _parse_entry(
        self,
        entry: dict[str, Any],
        *,
        as_detail: bool = False,
    ) -> ScraperGameDetail:
        tg_id = str(entry.get("uniqueId") or entry.get("unique_id") or entry.get("id") or "").strip()
        title = str(entry.get("name") or entry.get("title") or tg_id).strip()
        original_title = str(
            entry.get("originalName")
            or entry.get("original_name")
            or entry.get("subTitle")
            or entry.get("sub_title")
            or ""
        ).strip()
        if original_title == title:
            original_title = ""

        banner = str(
            entry.get("banner")
            or entry.get("cover")
            or entry.get("coverUrl")
            or entry.get("cover_url")
            or entry.get("image")
            or ""
        ).strip()
        bg_img = str(
            entry.get("background")
            or entry.get("backgroundUrl")
            or entry.get("hero")
            or banner
        ).strip()

        tags_raw = entry.get("tags") or []
        tags: list[str] = []
        if isinstance(tags_raw, list):
            for t in tags_raw:
                if isinstance(t, dict) and t.get("name"):
                    tags.append(str(t["name"]).strip())
                elif isinstance(t, str) and t.strip():
                    tags.append(t.strip())

        is_nsfw = bool(entry.get("nsfw", entry.get("isNsfw", entry.get("is_nsfw", False))))
        synopsis = _clean_text(
            entry.get("introduction")
            or entry.get("description")
            or entry.get("summary")
            or ""
        )

        developers = _extract_entity_names(
            entry.get("developers") or entry.get("developer") or entry.get("brand")
        )
        publishers = _extract_entity_names(
            entry.get("publishers") or entry.get("publisher")
        )
        cleaned_tags = clean_scraped_tags(
            tags,
            title=title,
            sub_title=original_title,
            developer=", ".join(developers),
            publisher=", ".join(publishers),
        )

        cover_url = banner if (self.allow_nsfw or not is_nsfw) else ""
        background_url = bg_img if (self.allow_nsfw or not is_nsfw) else ""
        source_url = str(entry.get("url") or "").strip() or (
            f"https://www.touchgal.io/{tg_id}" if tg_id else "https://developer.touchgal.com"
        )

        model_cls = ScraperGameDetail if as_detail else ScraperSearchResult
        return model_cls(
            source=self.source_id,
            source_id=tg_id,
            source_url=source_url,
            title=title,
            original_title=original_title,
            developers=developers,
            publishers=publishers,
            release_date=str(
                entry.get("releaseDate")
                or entry.get("release_date")
                or entry.get("publishDate")
                or entry.get("publish_date")
                or ""
            ).strip(),
            description=synopsis,
            tags=cleaned_tags,
            is_nsfw=is_nsfw,
            cover_url=cover_url,
            background_url=background_url,
            external_ids=normalize_external_ids({"touchgal": tg_id}),
        )

    @staticmethod
    def _extract_search_items(body: Any) -> list[dict[str, Any]] | None:
        """
        严格对齐 TouchGal 官方开发者 API v1 响应体：
        {"success": true, "data": {"items": [...]}}
        校验失败时返回 None。
        """
        if not isinstance(body, dict) or body.get("success") is not True:
            return None
        data = body.get("data")
        if not isinstance(data, dict):
            return None
        raw_items = data.get("items")
        if not isinstance(raw_items, list):
            return None
        return [item for item in raw_items if isinstance(item, dict)]

    @staticmethod
    def _extract_detail_entry(body: Any) -> dict[str, Any] | None:
        if not isinstance(body, dict) or body.get("success") is not True:
            return None
        data = body.get("data")
        if not isinstance(data, dict):
            return None
        if isinstance(data.get("game"), dict):
            data = data["game"]
        if data.get("uniqueId") or data.get("unique_id") or data.get("name") or data.get("title"):
            return data
        return None

    async def search(self, query: str, limit: int = 8) -> list[ScraperSearchResult]:
        q = (query or "").strip()
        if not q or not self.is_configured():
            return []

        direct_id = self.parse_direct_id(q)
        if direct_id:
            detail = await self.get_detail(direct_id)
            return [detail] if detail else []

        params = {
            "keyword": q[:100],
            "page": 1,
            "limit": max(1, min(int(limit), 50)),
        }

        async with self._build_client(headers=self._headers()) as client:
            try:
                resp = await client.get(f"{TOUCHGAL_API_BASE}/games/search", params=params)
                if resp.status_code != 200:
                    logger.debug(
                        "TouchGal API v1 search returned HTTP %s for %r",
                        resp.status_code,
                        q,
                    )
                    return []
                items_raw = self._extract_search_items(resp.json())
                if not items_raw:
                    return []
                items = [
                    self._parse_entry(item, as_detail=False)
                    for item in items_raw[:limit]
                ]
                if not self.allow_nsfw:
                    items = [it for it in items if not it.is_nsfw]
                return items
            except Exception as exc:
                logger.debug("TouchGal API v1 search failed: %s", exc)
        return []

    async def get_detail(self, source_id: str) -> ScraperGameDetail | None:
        raw = (source_id or "").strip()
        tg_id = self.parse_direct_id(raw) or raw
        if not tg_id or not self.is_configured():
            return None

        async with self._build_client(headers=self._headers()) as client:
            try:
                resp = await client.get(f"{TOUCHGAL_API_BASE}/games/{quote(tg_id, safe='')}")
                if resp.status_code != 200:
                    logger.debug(
                        "TouchGal API v1 detail returned HTTP %s for %r",
                        resp.status_code,
                        tg_id,
                    )
                    return None
                entry = self._extract_detail_entry(resp.json())
                if entry is not None:
                    return self._parse_entry(entry, as_detail=True)
            except Exception as exc:
                logger.debug("TouchGal API v1 detail failed for %r: %s", tg_id, exc)
        return None

    async def test_connection(self, timeout: float = 6.0) -> dict[str, Any]:
        if not self.is_configured():
            return {
                "ok": False,
                "source": self.source_id,
                "latency_ms": 0,
                "detail": "未配置 TouchGal API Key（格式如 tgal_live_<id>-<secret>）",
            }

        params = {
            "keyword": TOUCHGAL_TEST_KEYWORD,
            "page": 1,
            "limit": 1,
        }

        t0 = time.monotonic()
        per_req_timeout = max(2.0, min(timeout, 6.0))
        async with self._build_client(headers=self._headers(), timeout=per_req_timeout) as client:
            try:
                resp = await client.get(f"{TOUCHGAL_API_BASE}/games/search", params=params)
                elapsed = int((time.monotonic() - t0) * 1000)
                if resp.status_code in (401, 403):
                    return {
                        "ok": False,
                        "source": self.source_id,
                        "latency_ms": elapsed,
                        "detail": (
                            f"API Key 无效或无访问权限 (HTTP {resp.status_code})，"
                            "请核对 Key 格式是否为 tgal_live_<id>-<secret>（注意中间连字符 -）"
                        ),
                    }
                if resp.status_code == 429:
                    return {
                        "ok": False,
                        "source": self.source_id,
                        "latency_ms": elapsed,
                        "detail": "请求过于频繁，触发限流 (HTTP 429)",
                    }
                if resp.status_code == 200:
                    body = resp.json()
                    items = self._extract_search_items(body)
                    if items is not None:
                        return {
                            "ok": True,
                            "source": self.source_id,
                            "latency_ms": elapsed,
                            "sample_count": len(items),
                            "detail": f"连接正常 ({elapsed}ms)",
                        }
                    api_msg = ""
                    if isinstance(body, dict):
                        api_msg = str(body.get("message") or body.get("error") or "").strip()
                    return {
                        "ok": False,
                        "source": self.source_id,
                        "latency_ms": elapsed,
                        "detail": f"接口返回失败: {api_msg}" if api_msg else "接口响应格式异常（success 不为 true）",
                    }
                return {
                    "ok": False,
                    "source": self.source_id,
                    "latency_ms": elapsed,
                    "detail": f"接口返回异常 (HTTP {resp.status_code})",
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
