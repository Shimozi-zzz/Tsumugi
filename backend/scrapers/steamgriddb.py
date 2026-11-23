from __future__ import annotations

import asyncio
import hashlib
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
    normalize_external_ids,
)

logger = logging.getLogger("tsumugi.scrapers.steamgriddb")

SGDB_API_BASE = "https://www.steamgriddb.com/api/v2"

_SGDB_URL_RE = re.compile(
    r"https?://(?:www\.)?steamgriddb\.com/game/(\d+)",
    re.IGNORECASE,
)
_SGDB_PREFIX_RE = re.compile(r"^(?:sgdb|steamgriddb)[:/#\s-]?(\d+)$", re.IGNORECASE)


def _safe_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        n = int(round(float(val)))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


class SteamGridDBScraper(BaseScraper):
    """SteamGridDB API v2 刮削器（专精高清 600×900 竖版封面 Grid、宽屏背景 Hero 与透明 Logo）"""

    source_id = "steamgriddb"
    source_name = "SGDB"
    display_name = "SteamGridDB"
    requires_api_key = True
    categories = ()
    default_timeout = 8.0

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    def _nsfw_param(self) -> str:
        return "any" if self.allow_nsfw else "false"

    def parse_direct_id(self, query: str) -> str | None:
        raw = (query or "").strip()
        if not raw:
            return None
        m = _SGDB_URL_RE.search(raw)
        if m:
            return m.group(1)
        m2 = _SGDB_PREFIX_RE.match(raw)
        if m2:
            return m2.group(1)
        return None

    async def _fetch_asset_list(
        self,
        client,
        endpoint: str,
        params: dict[str, Any],
        *,
        game_title: str = "",
        kind: str = "cover",
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        try:
            resp = await client.get(f"{SGDB_API_BASE}{endpoint}", params=params)
            if resp.status_code != 200:
                return []
            items = resp.json().get("data") or []
            out: list[dict[str, Any]] = []
            seen: set[str] = set()
            for it in items:
                if not isinstance(it, dict):
                    continue
                mime = str(it.get("mime") or "").lower()
                if mime and mime not in ("image/png", "image/webp", "image/jpeg"):
                    continue
                url = str(it.get("url") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                thumb = str(it.get("thumb") or url).strip()
                digest = hashlib.sha1(f"sgdb:{kind}:{url}".encode("utf-8")).hexdigest()[:12]
                out.append(
                    {
                        "id": f"sgdb-{kind}-{digest}",
                        "source": self.source_id,
                        "source_name": self.display_name,
                        "url": url,
                        "thumb_url": thumb,
                        "title": game_title or "SteamGridDB",
                        "width": _safe_int(it.get("width")),
                        "height": _safe_int(it.get("height")),
                        "kind": kind,
                    }
                )
                if len(out) >= limit:
                    break
            return out
        except Exception as exc:
            logger.debug("SGDB asset list %s failed: %s", endpoint, exc)
            return []

    async def _fetch_best_asset(
        self, client, endpoint: str, params: dict[str, Any]
    ) -> str:
        items = await self._fetch_asset_list(client, endpoint, params, limit=1)
        return items[0]["url"] if items else ""

    async def find_id_by_steam_appid(self, steam_appid: str) -> str:
        if not self.api_key or not steam_appid:
            return ""
        try:
            async with self._build_client(headers=self._auth_headers()) as client:
                resp = await client.get(f"{SGDB_API_BASE}/games/steam/{steam_appid}")
                if resp.status_code != 200:
                    return ""
                data = resp.json().get("data") or {}
                return str(data.get("id") or "")
        except Exception as exc:
            logger.debug("SGDB lookup by steam appid %s failed: %s", steam_appid, exc)
            return ""

    async def fetch_visual_candidates(
        self,
        *,
        query: str = "",
        steam_appid: str = "",
        limit: int = 8,
    ) -> dict[str, list[dict[str, Any]]]:
        """按 steam_appid 或游戏名并发拉取高清 600×900 竖版封面、宽屏 Hero 背景与透明 Logo"""
        if not self.is_configured():
            return {"covers": [], "backgrounds": [], "logos": []}

        nsfw = self._nsfw_param()
        try:
            async with self._build_client(headers=self._auth_headers()) as client:
                sgdb_id = ""
                game_title = query.strip()

                if steam_appid and steam_appid.strip().isdigit():
                    resp = await client.get(f"{SGDB_API_BASE}/games/steam/{steam_appid.strip()}")
                    if resp.status_code == 200:
                        data = resp.json().get("data") or {}
                        sgdb_id = str(data.get("id") or "").strip()
                        game_title = str(data.get("name") or game_title).strip()

                if not sgdb_id and query.strip():
                    resp = await client.get(
                        f"{SGDB_API_BASE}/search/autocomplete/{quote(query.strip())}"
                    )
                    if resp.status_code == 200:
                        games = resp.json().get("data") or []
                        if games and isinstance(games[0], dict):
                            sgdb_id = str(games[0].get("id") or "").strip()
                            game_title = str(games[0].get("name") or game_title).strip()

                if not sgdb_id:
                    return {"covers": [], "backgrounds": [], "logos": []}

                covers, heroes, logos = await asyncio.gather(
                    self._fetch_asset_list(
                        client,
                        f"/grids/game/{sgdb_id}",
                        {"dimensions": "600x900,342x482", "nsfw": nsfw, "limit": limit},
                        game_title=game_title,
                        kind="cover",
                        limit=limit,
                    ),
                    self._fetch_asset_list(
                        client,
                        f"/heroes/game/{sgdb_id}",
                        {"nsfw": nsfw, "limit": limit},
                        game_title=game_title,
                        kind="background",
                        limit=limit,
                    ),
                    self._fetch_asset_list(
                        client,
                        f"/logos/game/{sgdb_id}",
                        {"nsfw": nsfw, "limit": min(limit, 6)},
                        game_title=game_title,
                        kind="logo",
                        limit=min(limit, 6),
                    ),
                    return_exceptions=True,
                )
                return {
                    "covers": [] if isinstance(covers, Exception) else covers,
                    "backgrounds": [] if isinstance(heroes, Exception) else heroes,
                    "logos": [] if isinstance(logos, Exception) else logos,
                }
        except Exception as exc:
            logger.debug("SGDB fetch_visual_candidates failed: %s", exc)
            return {"covers": [], "backgrounds": [], "logos": []}

    async def search(self, query: str, limit: int = 8) -> list[ScraperSearchResult]:
        q = (query or "").strip()
        if not q or not self.is_configured():
            return []

        direct_id = self.parse_direct_id(q)
        if direct_id:
            detail = await self.get_detail(direct_id)
            return [detail] if detail else []

        try:
            async with self._build_client(headers=self._auth_headers()) as client:
                resp = await client.get(f"{SGDB_API_BASE}/search/autocomplete/{quote(q)}")
                resp.raise_for_status()
                items = resp.json().get("data") or []
        except Exception as exc:
            logger.warning("SteamGridDB search failed for %r: %s", q, exc)
            return []

        results: list[ScraperSearchResult] = []
        for entry in items[:limit]:
            if not isinstance(entry, dict):
                continue
            sgdb_id = str(entry.get("id") or "").strip()
            if not sgdb_id:
                continue
            results.append(
                ScraperSearchResult(
                    source=self.source_id,
                    source_id=sgdb_id,
                    source_url=f"https://www.steamgriddb.com/game/{sgdb_id}",
                    title=str(entry.get("name") or sgdb_id),
                    external_ids=normalize_external_ids({"steamgriddb": sgdb_id}),
                )
            )
        return results

    async def get_detail(self, source_id: str) -> ScraperGameDetail | None:
        raw = (source_id or "").strip()
        sgdb_id = self.parse_direct_id(raw) or raw
        if not sgdb_id or not self.is_configured():
            return None

        nsfw = self._nsfw_param()
        try:
            async with self._build_client(headers=self._auth_headers()) as client:
                game_resp_coro = client.get(f"{SGDB_API_BASE}/games/id/{sgdb_id}")
                cover_coro = self._fetch_best_asset(
                    client,
                    f"/grids/game/{sgdb_id}",
                    {"dimensions": "600x900,342x482", "nsfw": nsfw, "limit": 10},
                )
                logo_coro = self._fetch_best_asset(
                    client,
                    f"/logos/game/{sgdb_id}",
                    {"nsfw": nsfw, "limit": 10},
                )
                hero_coro = self._fetch_best_asset(
                    client,
                    f"/heroes/game/{sgdb_id}",
                    {"nsfw": nsfw, "limit": 10},
                )

                game_resp, cover_url, logo_url, hero_url = await asyncio.gather(
                    game_resp_coro,
                    cover_coro,
                    logo_coro,
                    hero_coro,
                    return_exceptions=True,
                )

                title = sgdb_id
                if not isinstance(game_resp, Exception) and game_resp.status_code == 200:
                    gdata = game_resp.json().get("data") or {}
                    title = str(gdata.get("name") or sgdb_id)

                return ScraperGameDetail(
                    source=self.source_id,
                    source_id=sgdb_id,
                    source_url=f"https://www.steamgriddb.com/game/{sgdb_id}",
                    title=title,
                    cover_url="" if isinstance(cover_url, Exception) else cover_url,
                    logo_url="" if isinstance(logo_url, Exception) else logo_url,
                    background_url="" if isinstance(hero_url, Exception) else hero_url,
                    external_ids=normalize_external_ids({"steamgriddb": sgdb_id}),
                )
        except Exception as exc:
            logger.warning("SteamGridDB get_detail failed for %r: %s", sgdb_id, exc)
            return None

    async def test_connection(self, timeout: float = 6.0) -> dict[str, Any]:
        if not self.is_configured():
            return {
                "ok": False,
                "source": self.source_id,
                "latency_ms": 0,
                "detail": "未配置 API Key",
            }
        t0 = time.monotonic()
        try:
            async with self._build_client(headers=self._auth_headers(), timeout=timeout) as client:
                resp = await client.get(f"{SGDB_API_BASE}/search/autocomplete/Portal")
                elapsed = int((time.monotonic() - t0) * 1000)
                if resp.status_code in (401, 403):
                    return {
                        "ok": False,
                        "source": self.source_id,
                        "latency_ms": elapsed,
                        "detail": "API Key 无效或权限不足",
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
                items = resp.json().get("data") or []
                return {
                    "ok": True,
                    "source": self.source_id,
                    "latency_ms": elapsed,
                    "sample_count": len(items),
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
