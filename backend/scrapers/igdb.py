from __future__ import annotations

from datetime import datetime, timezone
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

logger = logging.getLogger("tsumugi.scrapers.igdb")

TWITCH_OAUTH_URL = "https://id.twitch.tv/oauth2/token"
IGDB_GAMES_URL = "https://api.igdb.com/v4/games"

_IGDB_URL_RE = re.compile(
    r"https?://(?:www\.)?igdb\.com/games/([a-zA-Z0-9_-]+)",
    re.IGNORECASE,
)
_IGDB_PREFIX_RE = re.compile(r"^igdb[:/#\s-]?(\d+)$", re.IGNORECASE)
_STEAM_APP_RE = re.compile(r"store\.steampowered\.com/app/(\d+)", re.IGNORECASE)

_IGDB_FIELDS = (
    "fields id, name, slug, url, summary, storyline, first_release_date, "
    "rating, total_rating, "
    "alternative_names.name, "
    "cover.image_id, "
    "artworks.image_id, "
    "screenshots.image_id, "
    "genres.name, themes.name, "
    "involved_companies.company.name, involved_companies.developer, involved_companies.publisher, "
    "websites.url;"
)

# 进程级 Twitch App Access Token 缓存：key = (client_id, client_secret) -> (token, expire_ts)
_TWITCH_TOKEN_CACHE: dict[tuple[str, str], tuple[str, float]] = {}


def _igdb_image_url(image_id: str | None, size: str = "t_cover_big_2x") -> str:
    clean = str(image_id or "").strip()
    if not clean:
        return ""
    return f"https://images.igdb.com/igdb/image/upload/{size}/{clean}.jpg"


def _escape_apicalypse(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace(";", "")


def _format_unix_date(ts: Any) -> str:
    if ts is None:
        return ""
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


class IGDBScraper(BaseScraper):
    """IGDB API v4 刮削器（通过 Twitch OAuth2 鉴权，补足主机独占与非 Steam 综合单机元数据）"""

    source_id = "igdb"
    source_name = "IGDB"
    display_name = "IGDB"
    requires_api_key = True
    categories = ("general",)
    default_timeout = 8.0

    def __init__(
        self,
        proxy_url: str = "",
        client_id: str = "",
        client_secret: str = "",
        allow_nsfw: bool = True,
        timeout: float | None = None,
    ) -> None:
        super().__init__(
            proxy_url=proxy_url,
            api_key=client_secret,
            allow_nsfw=allow_nsfw,
            timeout=timeout,
        )
        self.client_id = (client_id or "").strip()
        self.client_secret = (client_secret or "").strip()

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def parse_direct_id(self, query: str) -> str | None:
        raw = (query or "").strip()
        if not raw:
            return None
        m = _IGDB_URL_RE.search(raw)
        if m:
            return f"slug:{m.group(1)}"
        m2 = _IGDB_PREFIX_RE.match(raw)
        if m2:
            return m2.group(1)
        return None

    async def _get_access_token(self, client, *, force_refresh: bool = False) -> str:
        if not self.is_configured():
            return ""
        cache_key = (self.client_id, self.client_secret)
        now = time.monotonic()
        if not force_refresh and cache_key in _TWITCH_TOKEN_CACHE:
            token, exp = _TWITCH_TOKEN_CACHE[cache_key]
            if token and exp > now + 60:
                return token

        resp = await client.post(
            TWITCH_OAUTH_URL,
            params={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        token = str(data.get("access_token") or "").strip()
        expires_in = int(data.get("expires_in") or 3600)
        if token:
            _TWITCH_TOKEN_CACHE[cache_key] = (token, now + max(120, expires_in - 120))
        return token

    async def _query_games(self, body: str) -> list[dict[str, Any]]:
        if not self.is_configured():
            return []
        async with self._build_client() as client:
            token = await self._get_access_token(client, force_refresh=False)
            if not token:
                return []
            headers = {
                "Client-ID": self.client_id,
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "text/plain",
            }
            resp = await client.post(IGDB_GAMES_URL, content=body.encode("utf-8"), headers=headers)
            if resp.status_code == 401:
                token = await self._get_access_token(client, force_refresh=True)
                if not token:
                    return []
                headers["Authorization"] = f"Bearer {token}"
                resp = await client.post(IGDB_GAMES_URL, content=body.encode("utf-8"), headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

    def _parse_game(self, entry: dict[str, Any], *, as_detail: bool = False) -> ScraperGameDetail:
        igdb_id = str(entry.get("id") or "").strip()
        title = str(entry.get("name") or igdb_id).strip()
        slug = str(entry.get("slug") or "").strip()
        source_url = str(entry.get("url") or (f"https://www.igdb.com/games/{slug}" if slug else "")).strip()

        aliases: list[str] = []
        for alt in entry.get("alternative_names") or []:
            if isinstance(alt, dict) and alt.get("name"):
                n = str(alt["name"]).strip()
                if n and n != title and n not in aliases:
                    aliases.append(n)

        developers: list[str] = []
        publishers: list[str] = []
        for ic in entry.get("involved_companies") or []:
            if not isinstance(ic, dict):
                continue
            comp = ic.get("company")
            cname = str(comp.get("name") if isinstance(comp, dict) else "").strip()
            if not cname:
                continue
            if ic.get("developer") and cname not in developers:
                developers.append(cname)
            if ic.get("publisher") and cname not in publishers:
                publishers.append(cname)

        release_date = _format_unix_date(entry.get("first_release_date"))
        description = str(entry.get("summary") or entry.get("storyline") or "").strip()

        raw_tags: list[str] = []
        for group_key in ("genres", "themes"):
            for item in entry.get(group_key) or []:
                if isinstance(item, dict) and item.get("name"):
                    raw_tags.append(str(item["name"]))
        tags = clean_scraped_tags(
            raw_tags,
            title=title,
            developer=", ".join(developers),
            publisher=", ".join(publishers),
        )

        cover_obj = entry.get("cover") if isinstance(entry.get("cover"), dict) else {}
        cover_url = _igdb_image_url(cover_obj.get("image_id"), "t_cover_big_2x")

        screenshots: list[str] = []
        for ss in (entry.get("screenshots") or [])[:10]:
            if isinstance(ss, dict) and ss.get("image_id"):
                screenshots.append(_igdb_image_url(ss["image_id"], "t_1080p"))

        background_url = ""
        artworks = entry.get("artworks") or []
        if artworks and isinstance(artworks[0], dict) and artworks[0].get("image_id"):
            background_url = _igdb_image_url(artworks[0]["image_id"], "t_1080p")
        elif screenshots:
            background_url = screenshots[0]

        ext: dict[str, str] = {"igdb": igdb_id} if igdb_id else {}
        for site in entry.get("websites") or []:
            if isinstance(site, dict) and site.get("url"):
                m = _STEAM_APP_RE.search(str(site["url"]))
                if m and "steam" not in ext:
                    ext["steam"] = m.group(1)

        rating: float | None = None
        raw_rating = entry.get("total_rating") or entry.get("rating")
        if raw_rating is not None:
            try:
                rating = round(float(raw_rating) / 10.0, 2)
            except (TypeError, ValueError):
                pass

        is_nsfw = any(t.lower() in ("erotic", "adult") for t in raw_tags)
        model_cls = ScraperGameDetail if as_detail else ScraperSearchResult
        return model_cls(
            source=self.source_id,
            source_id=igdb_id,
            source_url=source_url,
            title=title,
            original_title="",
            aliases=aliases,
            developers=developers,
            publishers=publishers,
            release_date=release_date,
            description=description,
            tags=tags,
            cover_url=cover_url if (self.allow_nsfw or not is_nsfw) else "",
            background_url=background_url if (self.allow_nsfw or not is_nsfw) else "",
            external_ids=normalize_external_ids(ext),
            is_nsfw=is_nsfw,
            rating=rating,
            screenshots=screenshots,
        )

    async def search(self, query: str, limit: int = 8) -> list[ScraperSearchResult]:
        if not self.is_configured():
            return []
        q = (query or "").strip()
        if not q:
            return []

        direct_id = self.parse_direct_id(q)
        if direct_id:
            detail = await self.get_detail(direct_id)
            return [detail] if detail else []

        capped = max(1, min(limit, 20))
        safe_q = _escape_apicalypse(q)
        body = f'{_IGDB_FIELDS} search "{safe_q}"; limit {capped};'
        try:
            entries = await self._query_games(body)
            return [self._parse_game(item, as_detail=False) for item in entries if isinstance(item, dict)]
        except Exception as exc:
            logger.warning("IGDB search failed for %r: %s", q, exc)
            return []

    async def get_detail(self, source_id: str) -> ScraperGameDetail | None:
        if not self.is_configured():
            return None
        raw = (source_id or "").strip()
        parsed = self.parse_direct_id(raw) or raw
        if not parsed:
            return None

        if parsed.startswith("slug:"):
            slug = _escape_apicalypse(parsed[5:].strip())
            if not slug:
                return None
            body = f'{_IGDB_FIELDS} where slug = "{slug}"; limit 1;'
        elif parsed.isdigit():
            body = f"{_IGDB_FIELDS} where id = {int(parsed)}; limit 1;"
        else:
            return None

        try:
            entries = await self._query_games(body)
            if not entries:
                return None
            return self._parse_game(entries[0], as_detail=True)
        except Exception as exc:
            logger.warning("IGDB get_detail failed for %r: %s", source_id, exc)
            return None

    async def test_connection(self, timeout: float = 6.0) -> dict[str, Any]:
        if not self.is_configured():
            return {
                "ok": False,
                "source": self.source_id,
                "latency_ms": 0,
                "detail": "未配置 API Key（需填写 Twitch Client ID 与 Client Secret）",
            }
        t0 = time.monotonic()
        try:
            async with self._build_client(timeout=timeout) as client:
                oauth_resp = await client.post(
                    TWITCH_OAUTH_URL,
                    params={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "grant_type": "client_credentials",
                    },
                )
                elapsed = int((time.monotonic() - t0) * 1000)
                if oauth_resp.status_code in (400, 401, 403):
                    return {
                        "ok": False,
                        "source": self.source_id,
                        "latency_ms": elapsed,
                        "detail": "Twitch Client ID 或 Client Secret 无效",
                    }
                if oauth_resp.status_code != 200:
                    return {
                        "ok": False,
                        "source": self.source_id,
                        "latency_ms": elapsed,
                        "detail": f"Twitch 鉴权接口异常 (HTTP {oauth_resp.status_code})",
                    }
                token = str((oauth_resp.json() or {}).get("access_token") or "").strip()
                if not token:
                    return {
                        "ok": False,
                        "source": self.source_id,
                        "latency_ms": elapsed,
                        "detail": "未获取到 Twitch OAuth Token",
                    }

                resp = await client.post(
                    IGDB_GAMES_URL,
                    content=b'fields id, name; limit 1;',
                    headers={
                        "Client-ID": self.client_id,
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "text/plain",
                    },
                )
                elapsed = int((time.monotonic() - t0) * 1000)
                if resp.status_code in (401, 403):
                    return {
                        "ok": False,
                        "source": self.source_id,
                        "latency_ms": elapsed,
                        "detail": f"IGDB 鉴权被拒 (HTTP {resp.status_code})",
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
                        "detail": f"IGDB 接口返回异常 (HTTP {resp.status_code})",
                    }
                entries = resp.json()
                return {
                    "ok": True,
                    "source": self.source_id,
                    "latency_ms": elapsed,
                    "sample_count": len(entries) if isinstance(entries, list) else 0,
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
                "detail": f"IGDB 验证失败: {exc}",
            }
