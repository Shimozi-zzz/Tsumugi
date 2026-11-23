from __future__ import annotations

import json
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

logger = logging.getLogger("tsumugi.scrapers.touchgal")

TOUCHGAL_ENDPOINTS = (
    "https://www.touchgal.io",
    "https://www.touchgal.top",
)

_HTML_RE = re.compile(r"<[^>]+>")
_TGAL_URL_RE = re.compile(
    r"https?://(?:www\.)?touchgal\.(?:io|top|us)/(?:galgame/|patch/)?([a-zA-Z0-9_-]{4,})",
    re.IGNORECASE,
)
_TGAL_PREFIX_RE = re.compile(
    r"^(?:touchgal|tgal)[:/#\s-]+([a-zA-Z0-9_-]{3,})$",
    re.IGNORECASE,
)
_TGAL_RESERVED_SLUGS = frozenset({"search", "login", "register", "about", "api", "home", "galgame", "patch"})


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s{3,}", "\n\n", _HTML_RE.sub("", value)).strip()


class TouchGalScraper(BaseScraper):
    """TouchGal 刮削器（专精中文 Galgame 译名、汉化简介与宽幅横版封面，支持第三方 API Key）"""

    source_id = "touchgal"
    source_name = "TGAL"
    display_name = "TouchGal"
    requires_api_key = True
    categories = ("galgame",)
    default_timeout = 8.0

    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": "TsumugiGameLibrary/0.9 (https://github.com/tsumugi-local)",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
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
        tg_id = str(entry.get("uniqueId") or entry.get("id") or "").strip()
        title = str(entry.get("name") or entry.get("title") or tg_id).strip()
        original_title = str(entry.get("originalName") or entry.get("subTitle") or "").strip()
        if original_title == title:
            original_title = ""

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
        developers = split_entity_names(developer)
        publishers = split_entity_names(publisher)
        cleaned_tags = clean_scraped_tags(
            tags,
            title=title,
            sub_title=original_title,
            developer=developer,
            publisher=publisher,
        )

        img_url = banner if (self.allow_nsfw or not is_nsfw) else ""
        model_cls = ScraperGameDetail if as_detail else ScraperSearchResult
        return model_cls(
            source=self.source_id,
            source_id=tg_id,
            source_url=f"https://www.touchgal.io/{tg_id}" if tg_id else "https://www.touchgal.io",
            title=title,
            original_title=original_title,
            developers=developers,
            publishers=publishers,
            release_date=str(entry.get("releaseDate") or entry.get("publishDate") or "").strip(),
            description=synopsis,
            tags=cleaned_tags,
            is_nsfw=is_nsfw,
            cover_url=img_url,
            background_url=img_url,
            external_ids=normalize_external_ids({"touchgal": tg_id}),
        )

    async def search(self, query: str, limit: int = 8) -> list[ScraperSearchResult]:
        q = (query or "").strip()
        if not q:
            return []

        direct_id = self.parse_direct_id(q)
        if direct_id:
            detail = await self.get_detail(direct_id)
            return [detail] if detail else []

        payload = {
            "queryString": json.dumps([{"type": "keyword", "name": q}], ensure_ascii=False),
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

        async with self._build_client(headers=self._headers()) as client:
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
                        items = [
                            self._parse_entry(item, as_detail=False)
                            for item in raw_list[:limit]
                            if isinstance(item, dict)
                        ]
                        if not self.allow_nsfw:
                            items = [it for it in items if not it.is_nsfw]
                        return items
                except Exception as exc:
                    logger.debug("TouchGal search failed on %s: %s", base_url, exc)
                    continue
        return []

    async def get_detail(self, source_id: str) -> ScraperGameDetail | None:
        raw = (source_id or "").strip()
        tg_id = self.parse_direct_id(raw) or raw
        if not tg_id:
            return None

        async with self._build_client(headers=self._headers()) as client:
            for base_url in TOUCHGAL_ENDPOINTS:
                for path in (f"/api/galgame/{tg_id}", f"/api/patch/{tg_id}"):
                    try:
                        resp = await client.get(f"{base_url}{path}")
                        if resp.status_code != 200:
                            continue
                        data = resp.json()
                        entry = (
                            data.get("data")
                            if isinstance(data, dict) and isinstance(data.get("data"), dict)
                            else data
                        )
                        if isinstance(entry, dict) and (entry.get("name") or entry.get("title")):
                            return self._parse_entry(entry, as_detail=True)
                    except Exception as exc:
                        logger.debug("TouchGal detail failed on %s%s: %s", base_url, path, exc)
        return None

    async def test_connection(self, timeout: float = 6.0) -> dict[str, Any]:
        if not self.api_key:
            return {
                "ok": False,
                "source": self.source_id,
                "latency_ms": 0,
                "detail": "未配置 API Key",
            }

        payload = {
            "queryString": json.dumps([{"type": "keyword", "name": "CLANNAD"}], ensure_ascii=False),
            "limit": 1,
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

        t0 = time.monotonic()
        last_error = "无法连接到 TouchGal 服务"
        per_req_timeout = max(2.0, min(timeout, 6.0))
        async with self._build_client(headers=self._headers(), timeout=per_req_timeout) as client:
            for base_url in TOUCHGAL_ENDPOINTS:
                try:
                    resp = await client.post(f"{base_url}/api/search", json=payload)
                    elapsed = int((time.monotonic() - t0) * 1000)
                    if resp.status_code in (401, 403):
                        return {
                            "ok": False,
                            "source": self.source_id,
                            "latency_ms": elapsed,
                            "detail": f"API Key 无效或无访问权限 (HTTP {resp.status_code})",
                        }
                    if resp.status_code == 429:
                        return {
                            "ok": False,
                            "source": self.source_id,
                            "latency_ms": elapsed,
                            "detail": "请求过于频繁，触发限流 (HTTP 429)",
                        }
                    if resp.status_code == 200:
                        data = resp.json()
                        raw_list = (
                            data.get("galgames")
                            or data.get("data")
                            or data.get("results")
                            or (data if isinstance(data, list) else [])
                        )
                        return {
                            "ok": True,
                            "source": self.source_id,
                            "latency_ms": elapsed,
                            "sample_count": len(raw_list) if isinstance(raw_list, list) else 0,
                            "detail": f"连接正常 ({elapsed}ms)",
                        }
                    last_error = f"接口返回异常 (HTTP {resp.status_code})"
                except httpx.TimeoutException:
                    last_error = f"连接超时 (>{timeout:.0f}s)"
                except Exception as exc:
                    last_error = f"连接失败: {exc}"

        elapsed = int((time.monotonic() - t0) * 1000)
        return {
            "ok": False,
            "source": self.source_id,
            "latency_ms": elapsed,
            "detail": last_error,
        }
