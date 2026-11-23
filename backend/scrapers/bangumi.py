from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.parse import quote

import httpx

from backend.scrapers.base import (
    BaseScraper,
    ScraperGameDetail,
    ScraperSearchResult,
    clean_scraped_tags,
    normalize_external_ids,
    split_entity_names,
)

logger = logging.getLogger("tsumugi.scrapers.bangumi")

BGM_BASE_URL = "https://api.bgm.tv"
BANGUMI_USER_AGENT = "Shimozi/Tsumugi (https://github.com/tsumugi-platform)"

_BGM_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:bgm\.tv|bangumi\.tv|chii\.in)/subject/(\d+)",
    re.IGNORECASE,
)
_BGM_PREFIX_RE = re.compile(r"^(?:bgm|bangumi)[:/#\s-]?(?:subject/)?(\d+)$", re.IGNORECASE)


def _extract_infobox_values(infobox: list[dict[str, Any]] | None, target_keys: set[str]) -> list[str]:
    values: list[str] = []
    if not infobox:
        return values
    for entry in infobox:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        if key not in target_keys:
            continue
        val = entry.get("value")
        if isinstance(val, str) and val.strip():
            values.append(val.strip())
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and item.get("v"):
                    s = str(item["v"]).strip()
                    if s:
                        values.append(s)
                elif isinstance(item, str) and item.strip():
                    values.append(item.strip())
    return values


def _extract_infobox_value(infobox: list[dict[str, Any]] | None, target_keys: set[str]) -> str:
    vals = _extract_infobox_values(infobox, target_keys)
    return ", ".join(dict.fromkeys(vals))


class BangumiScraper(BaseScraper):
    """Bangumi API v0 刮削器（type=4 游戏分类，支持 subject 链接直查与可选 Access Token）"""

    source_id = "bangumi"
    source_name = "BGM"
    display_name = "Bangumi"
    requires_api_key = False
    categories = ("galgame", "general")
    default_timeout = 8.0

    def _auth_headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": BANGUMI_USER_AGENT,
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def parse_direct_id(self, query: str) -> str | None:
        raw = (query or "").strip()
        if not raw:
            return None
        m = _BGM_URL_RE.search(raw)
        if m:
            return m.group(1)
        m2 = _BGM_PREFIX_RE.match(raw)
        if m2:
            return m2.group(1)
        return None

    def _parse_subject(
        self,
        item: dict[str, Any],
        *,
        as_detail: bool = False,
    ) -> ScraperGameDetail:
        bgm_id = str(item.get("id") or "").strip()
        name_cn = str(item.get("name_cn") or "").strip()
        name_orig = str(item.get("name") or "").strip()

        title = name_cn or name_orig or bgm_id
        original_title = name_orig if (name_cn and name_orig and name_orig != name_cn) else ""

        infobox = item.get("infobox") or []
        aliases = [
            a
            for a in dict.fromkeys(_extract_infobox_values(infobox, {"别名", "中文名", "英文名"}))
            if a and a != title and a != original_title
        ]

        dev_str = _extract_infobox_value(infobox, {"开发", "开发商", "制作", "游戏开发", "研发"})
        pub_str = _extract_infobox_value(infobox, {"发行", "发行商", "代理", "出品"})
        developers = split_entity_names(dev_str)
        publishers = split_entity_names(pub_str)

        release_date = (
            str(item.get("date") or "").strip()
            or _extract_infobox_value(infobox, {"发行日期", "发售日期", "发售日", "上市日期"})
        )

        raw_tags = item.get("tags") or []
        if raw_tags and isinstance(raw_tags[0], dict):
            sorted_tags = sorted(raw_tags, key=lambda t: int(t.get("count", 0)), reverse=True)
            candidate_tags = [str(t["name"]) for t in sorted_tags[:24] if t.get("name")]
        else:
            candidate_tags = [str(t) for t in (item.get("meta_tags") or [])[:24]]
        tags = clean_scraped_tags(
            candidate_tags,
            title=title,
            sub_title=original_title,
            developer=dev_str,
            publisher=pub_str,
        )

        images = item.get("images") or {}
        cover_url = (
            images.get("large")
            or images.get("common")
            or images.get("medium")
            or images.get("grid")
            or ""
        )

        rating: float | None = None
        rating_obj = item.get("rating")
        if isinstance(rating_obj, dict) and rating_obj.get("score") is not None:
            try:
                score_val = float(rating_obj["score"])
                if score_val > 0:
                    rating = round(score_val, 2)
            except (TypeError, ValueError):
                pass
        elif item.get("score") is not None:
            try:
                score_val = float(item["score"])
                if score_val > 0:
                    rating = round(score_val, 2)
            except (TypeError, ValueError):
                pass

        is_nsfw = bool(item.get("nsfw", False))
        if not is_nsfw:
            nsfw_markers = {"R18", "18禁", "拔作", "黄油", "成人"}
            is_nsfw = any(t in nsfw_markers for t in tags)

        model_cls = ScraperGameDetail if as_detail else ScraperSearchResult
        return model_cls(
            source=self.source_id,
            source_id=bgm_id,
            source_url=f"https://bgm.tv/subject/{bgm_id}" if bgm_id else "https://bgm.tv",
            title=title,
            original_title=original_title,
            aliases=aliases,
            developers=developers,
            publishers=publishers,
            release_date=release_date,
            description=str(item.get("summary") or "").strip(),
            tags=tags,
            cover_url=str(cover_url),
            background_url="",
            external_ids=normalize_external_ids({"bangumi": bgm_id}),
            is_nsfw=is_nsfw,
            rating=rating,
        )

    async def search(self, query: str, limit: int = 8) -> list[ScraperSearchResult]:
        q = (query or "").strip()
        if not q:
            return []

        direct_id = self.parse_direct_id(q)
        if direct_id:
            detail = await self.get_detail(direct_id)
            return [detail] if detail else []

        capped = max(1, min(limit, 20))
        headers = self._auth_headers()

        payload: dict[str, Any] = {
            "keyword": q,
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
                    return [
                        self._parse_subject(it, as_detail=False)
                        for it in items
                        if isinstance(it, dict)
                    ]

                fallback_resp = await client.get(
                    f"{BGM_BASE_URL}/search/subject/{quote(q)}",
                    params={"type": 4, "responseGroup": "large", "max_results": capped},
                )
                fallback_resp.raise_for_status()
                fb_data = fallback_resp.json()
                fb_list = fb_data.get("list") or []
                return [
                    self._parse_subject(it, as_detail=False)
                    for it in fb_list
                    if isinstance(it, dict)
                ]
        except Exception as exc:
            logger.warning("Bangumi search failed for %r: %s", q, exc)
            return []

    async def get_detail(self, source_id: str) -> ScraperGameDetail | None:
        raw = (source_id or "").strip()
        bgm_id = self.parse_direct_id(raw) or raw
        if not bgm_id or not bgm_id.isdigit():
            return None
        try:
            async with self._build_client(headers=self._auth_headers()) as client:
                resp = await client.get(f"{BGM_BASE_URL}/v0/subjects/{bgm_id}")
                resp.raise_for_status()
                data = resp.json()
                return self._parse_subject(data, as_detail=True)
        except Exception as exc:
            logger.warning("Bangumi get_detail failed for %r: %s", bgm_id, exc)
            return None

    async def test_connection(self, timeout: float = 6.0) -> dict[str, Any]:
        t0 = time.monotonic()
        try:
            async with self._build_client(headers=self._auth_headers(), timeout=timeout) as client:
                if self.api_key:
                    resp = await client.get(f"{BGM_BASE_URL}/v0/me")
                    elapsed = int((time.monotonic() - t0) * 1000)
                    if resp.status_code in (401, 403):
                        return {
                            "ok": False,
                            "source": self.source_id,
                            "latency_ms": elapsed,
                            "detail": "Access Token 无效或已过期",
                        }
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
                    data = resp.json() if resp.content else {}
                    nick = str(data.get("nickname") or data.get("username") or "").strip()
                    suffix = f"，已认证 {nick}" if nick else "，Token 有效"
                    return {
                        "ok": True,
                        "source": self.source_id,
                        "latency_ms": elapsed,
                        "sample_count": 1,
                        "detail": f"连接正常 ({elapsed}ms{suffix})",
                    }

                resp = await client.post(
                    f"{BGM_BASE_URL}/v0/search/subjects",
                    params={"limit": 1, "offset": 0},
                    json={"keyword": "CLANNAD", "sort": "match", "filter": {"type": [4]}},
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
                items = data.get("data") if isinstance(data, dict) else []
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
