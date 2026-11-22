import asyncio
import logging
from typing import Any
from urllib.parse import quote

from backend.scrapers.base import BaseScraper, ScrapedGameItem

logger = logging.getLogger("tsumugi.scrapers.steamgriddb")

SGDB_API_BASE = "https://www.steamgriddb.com/api/v2"


class SteamGridDBScraper(BaseScraper):
    """SteamGridDB API v2 刮削器（专精透明艺术字 Logo、宽幅 Hero 背景与竖版 600x900 高清封面）"""

    source_name = "SGDB"

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    def _nsfw_param(self) -> str:
        return "any" if self.allow_nsfw else "false"

    async def _fetch_best_asset(
        self, client, endpoint: str, params: dict[str, Any]
    ) -> str:
        try:
            resp = await client.get(f"{SGDB_API_BASE}{endpoint}", params=params)
            if resp.status_code != 200:
                return ""
            items = resp.json().get("data") or []
            if not items:
                return ""
            # 优先选择 PNG/WebP 静态高清资产（避免超大动态图卡顿）
            preferred = [
                it for it in items
                if str(it.get("mime", "")).lower() in ("image/png", "image/webp", "image/jpeg")
            ]
            chosen = preferred[0] if preferred else items[0]
            return str(chosen.get("url") or "")
        except Exception as exc:
            logger.debug("SGDB asset fetch %s failed: %s", endpoint, exc)
            return ""

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

    async def search(self, keyword: str, limit: int = 8) -> list[ScrapedGameItem]:
        query = keyword.strip()
        if not query or not self.api_key:
            if not self.api_key:
                logger.info("SteamGridDB API Key 未配置，跳过 SGDB 检索")
            return []

        try:
            async with self._build_client(headers=self._auth_headers()) as client:
                resp = await client.get(
                    f"{SGDB_API_BASE}/search/autocomplete/{quote(query)}"
                )
                resp.raise_for_status()
                items = resp.json().get("data") or []
        except Exception as exc:
            logger.warning("SteamGridDB search failed for %r: %s", query, exc)
            return []

        results: list[ScrapedGameItem] = []
        for entry in items[:limit]:
            sgdb_id = str(entry.get("id", ""))
            if not sgdb_id:
                continue
            results.append(
                ScrapedGameItem(
                    source=self.source_name,
                    external_id=sgdb_id,
                    title=str(entry.get("name") or sgdb_id),
                    extra_ids={"sgdb": sgdb_id},
                )
            )
        return results

    async def get_detail(self, external_id: str) -> ScrapedGameItem | None:
        sgdb_id = external_id.strip()
        if not sgdb_id or not self.api_key:
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

                return ScrapedGameItem(
                    source=self.source_name,
                    external_id=sgdb_id,
                    title=title,
                    cover_url="" if isinstance(cover_url, Exception) else cover_url,
                    logo_url="" if isinstance(logo_url, Exception) else logo_url,
                    hero_bg_url="" if isinstance(hero_url, Exception) else hero_url,
                    extra_ids={"sgdb": sgdb_id},
                )
        except Exception as exc:
            logger.warning("SteamGridDB get_detail failed for %r: %s", sgdb_id, exc)
            return None
