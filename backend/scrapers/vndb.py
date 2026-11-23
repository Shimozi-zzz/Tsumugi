from __future__ import annotations

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
)

logger = logging.getLogger("tsumugi.scrapers.vndb")

VNDB_API_URL = "https://api.vndb.org/kana/vn"
VNDB_FIELDS = (
    "id, title, alttitle, aliases, titles.lang, titles.title, titles.main, "
    "released, description, rating, image.url, image.sexual, image.violence, "
    "developers.name, developers.original, "
    "tags.name, tags.spoiler, tags.rating, tags.category, "
    "screenshots.url, screenshots.sexual, screenshots.violence, "
    "extlinks.url, extlinks.id, extlinks.name, extlinks.label"
)

_BBCODE_URL_RE = re.compile(r"\[url=[^\]]*\](.*?)\[/url\]", re.IGNORECASE | re.DOTALL)
_BBCODE_SPOILER_RE = re.compile(r"\[spoiler\].*?\[/spoiler\]", re.IGNORECASE | re.DOTALL)
_BBCODE_TAG_RE = re.compile(r"\[/?[a-zA-Z0-9*=_-]+\]")

_VNDB_URL_RE = re.compile(r"https?://(?:www\.)?vndb\.org/v(\d+)", re.IGNORECASE)
_VNDB_ID_RE = re.compile(r"^v(\d+)$", re.IGNORECASE)
_VNDB_PREFIX_RE = re.compile(r"^vndb[:/#\s-]?v?(\d+)$", re.IGNORECASE)

_STEAM_APP_RE = re.compile(r"store\.steampowered\.com/app/(\d+)", re.IGNORECASE)
_DLSITE_CODE_RE = re.compile(r"\b((?:RJ|VJ|BJ)\d{4,10})\b", re.IGNORECASE)
_BGM_URL_RE = re.compile(r"(?:bgm\.tv|bangumi\.tv)/subject/(\d+)", re.IGNORECASE)
_YMGAL_URL_RE = re.compile(r"ymgal\.games/[gG][aA](\d+)", re.IGNORECASE)


def _clean_vndb_bbcode(text: str | None) -> str:
    if not text:
        return ""
    cleaned = _BBCODE_SPOILER_RE.sub("", text)
    cleaned = _BBCODE_URL_RE.sub(r"\1", cleaned)
    cleaned = _BBCODE_TAG_RE.sub("", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


class VNDBScraper(BaseScraper):
    """VNDB Kana API v2 刮削器（免 Key，支持 v{id} / 链接直查、原名别名与 Steam/DLsite 外链提取）"""

    source_id = "vndb"
    source_name = "VNDB"
    display_name = "VNDB"
    requires_api_key = False
    categories = ("galgame",)
    default_timeout = 8.0

    def parse_direct_id(self, query: str) -> str | None:
        raw = (query or "").strip()
        if not raw:
            return None
        m = _VNDB_URL_RE.search(raw)
        if m:
            return f"v{m.group(1)}"
        m2 = _VNDB_ID_RE.match(raw)
        if m2:
            return f"v{m2.group(1)}"
        m3 = _VNDB_PREFIX_RE.match(raw)
        if m3:
            return f"v{m3.group(1)}"
        return None

    def _parse_vn_entry(
        self,
        entry: dict[str, Any],
        *,
        as_detail: bool = False,
    ) -> ScraperGameDetail:
        vn_id = str(entry.get("id") or "").strip()
        default_title = str(entry.get("title") or "").strip()
        alt_title = str(entry.get("alttitle") or "").strip()

        zh_title = ""
        ja_title = alt_title
        aliases: list[str] = []

        for t in entry.get("titles") or []:
            if not isinstance(t, dict):
                continue
            lang = str(t.get("lang") or "").lower()
            t_str = str(t.get("title") or "").strip()
            if not t_str:
                continue
            if lang == "zh-hans" and not zh_title:
                zh_title = t_str
            elif lang == "zh-hant" and not zh_title:
                zh_title = t_str
            elif lang == "ja" and not ja_title:
                ja_title = t_str
            if t_str not in aliases:
                aliases.append(t_str)

        for raw_alias in entry.get("aliases") or []:
            s = str(raw_alias or "").strip()
            if s and s not in aliases:
                aliases.append(s)

        display_title = zh_title or default_title or ja_title or vn_id
        original_title = next(
            (c for c in (ja_title, default_title) if c and c != display_title),
            "",
        )
        aliases = [a for a in aliases if a != display_title and a != original_title]
        if default_title and default_title != display_title and default_title != original_title and default_title not in aliases:
            aliases.insert(0, default_title)

        devs: list[str] = []
        for dev in entry.get("developers") or []:
            if not isinstance(dev, dict):
                continue
            name = str(dev.get("original") or dev.get("name") or "").strip()
            if name and name not in devs:
                devs.append(name)

        raw_tags = entry.get("tags") or []
        safe_tags = [
            t
            for t in raw_tags
            if isinstance(t, dict) and int(t.get("spoiler", 0)) == 0 and float(t.get("rating", 0)) >= 1.8
        ]
        safe_tags.sort(key=lambda t: float(t.get("rating", 0)), reverse=True)
        tags = clean_scraped_tags(
            [str(t["name"]) for t in safe_tags[:24] if t.get("name")],
            title=display_title,
            sub_title=original_title,
            developer=", ".join(devs),
        )

        image_obj = entry.get("image") or {}
        img_sexual = float(image_obj.get("sexual") or 0)
        img_violence = float(image_obj.get("violence") or 0)
        is_nsfw = img_sexual >= 1.0 or any(
            isinstance(t, dict) and t.get("category") == "ero" and float(t.get("rating", 0)) >= 1.5
            for t in raw_tags
        )

        cover_url = ""
        if image_obj.get("url"):
            if self.allow_nsfw or (img_sexual < 1.0 and img_violence < 1.0):
                cover_url = str(image_obj["url"])

        screenshots: list[str] = []
        for ss in entry.get("screenshots") or []:
            if not isinstance(ss, dict):
                continue
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

        # 提取 extlinks 中的 Steam / DLsite / Bangumi / YMGal 关联 ID
        ext_ids: dict[str, str] = {"vndb": vn_id}
        for link in entry.get("extlinks") or []:
            if not isinstance(link, dict):
                continue
            url = str(link.get("url") or "")
            link_name = str(link.get("name") or "").lower()
            link_id = str(link.get("id") or "").strip()

            if "steam" not in ext_ids:
                if link_name == "steam" and link_id.isdigit():
                    ext_ids["steam"] = link_id
                else:
                    m_steam = _STEAM_APP_RE.search(url)
                    if m_steam:
                        ext_ids["steam"] = m_steam.group(1)

            if "dlsite" not in ext_ids:
                m_dl = _DLSITE_CODE_RE.search(url) or (
                    _DLSITE_CODE_RE.search(link_id) if "dlsite" in link_name else None
                )
                if m_dl:
                    ext_ids["dlsite"] = m_dl.group(1).upper()

            if "bangumi" not in ext_ids:
                m_bgm = _BGM_URL_RE.search(url)
                if m_bgm:
                    ext_ids["bangumi"] = m_bgm.group(1)

            if "ymgal" not in ext_ids:
                m_ym = _YMGAL_URL_RE.search(url)
                if m_ym:
                    ext_ids["ymgal"] = f"GA{m_ym.group(1)}"

        released = str(entry.get("released") or "").strip()
        if released.upper() == "TBA":
            released = ""

        rating: float | None = None
        if entry.get("rating") is not None:
            try:
                rating = round(float(entry["rating"]) / 10.0, 2)
            except (TypeError, ValueError):
                pass

        model_cls = ScraperGameDetail if as_detail else ScraperSearchResult
        return model_cls(
            source=self.source_id,
            source_id=vn_id,
            source_url=f"https://vndb.org/{vn_id}" if vn_id else "https://vndb.org",
            title=display_title,
            original_title=original_title,
            aliases=aliases,
            developers=devs,
            publishers=[],
            release_date=released,
            description=_clean_vndb_bbcode(entry.get("description")),
            tags=tags,
            cover_url=cover_url,
            background_url=screenshots[0] if screenshots else "",
            external_ids=normalize_external_ids(ext_ids),
            is_nsfw=is_nsfw,
            rating=rating,
            screenshots=screenshots,
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
            "filters": ["search", "=", q],
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
            logger.warning("VNDB search failed for %r: %s", q, exc)
            return []

        results = data.get("results") or []
        return [self._parse_vn_entry(item, as_detail=False) for item in results if isinstance(item, dict)]

    async def get_detail(self, source_id: str) -> ScraperGameDetail | None:
        raw = (source_id or "").strip()
        vn_id = self.parse_direct_id(raw) or raw
        if not vn_id:
            return None
        if vn_id.isdigit():
            vn_id = f"v{vn_id}"
        elif vn_id.lower().startswith("v") and vn_id[1:].isdigit():
            vn_id = f"v{vn_id[1:]}"
        else:
            return None

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
        return self._parse_vn_entry(results[0], as_detail=True)

    async def test_connection(self, timeout: float = 6.0) -> dict[str, Any]:
        t0 = time.monotonic()
        payload = {
            "filters": ["id", "=", "v4"],
            "fields": "id, title",
            "results": 1,
        }
        try:
            async with self._build_client(timeout=timeout) as client:
                resp = await client.post(VNDB_API_URL, json=payload)
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
                results = data.get("results") if isinstance(data, dict) else []
                return {
                    "ok": True,
                    "source": self.source_id,
                    "latency_ms": elapsed,
                    "sample_count": len(results) if isinstance(results, list) else 0,
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
