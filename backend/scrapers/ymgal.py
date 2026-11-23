from __future__ import annotations

import html
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

logger = logging.getLogger("tsumugi.scrapers.ymgal")

YMGAL_BASE_URL = "https://www.ymgal.games"
YMGAL_OAUTH_URL = f"{YMGAL_BASE_URL}/oauth/token"
YMGAL_SEARCH_URL = f"{YMGAL_BASE_URL}/open/archive/search-game"
YMGAL_ARCHIVE_URL = f"{YMGAL_BASE_URL}/open/archive"

# 月幕开放平台官方文档提供的公共只读实验凭证（作为未配置自定义 Client 时的公开只读兜底）
YMGAL_PUBLIC_CLIENT_ID = "ymgal"
YMGAL_PUBLIC_CLIENT_SECRET = "luna0327"

_YMGAL_URL_RE = re.compile(
    r"https?://(?:www\.)?ymgal\.games/[gG][aA](\d+)",
    re.IGNORECASE,
)
_YMGAL_ID_RE = re.compile(r"^[gG][aA](\d+)$")
_YMGAL_PREFIX_RE = re.compile(r"^ymgal[:/#\s-]?(?:[gG][aA])?(\d+)$", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_STEAM_APP_RE = re.compile(r"store\.steampowered\.com/app/(\d+)", re.IGNORECASE)
_VNDB_ID_RE = re.compile(r"vndb\.org/v(\d+)", re.IGNORECASE)
_BGM_ID_RE = re.compile(r"(?:bgm\.tv|bangumi\.tv)/subject/(\d+)", re.IGNORECASE)
_DLSITE_CODE_RE = re.compile(r"dlsite\.com/[^/\s]+/(?:work|announce)/=/product_id/((?:RJ|VJ|BJ)\d+)", re.IGNORECASE)
_META_TAG_RE = re.compile(
    r'<meta\s+[^>]*?(?:property|name)=["\']([^"\']+)["\'][^>]*?content=["\']([^"\']*)["\']',
    re.IGNORECASE,
)

# 进程级 Token 缓存：key = (client_id, client_secret) -> (access_token, expire_ts)
_TOKEN_CACHE: dict[tuple[str, str], tuple[str, float]] = {}


def _clean_text(raw: Any) -> str:
    if not raw:
        return ""
    text = str(raw).replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _normalize_image_url(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if s.startswith("//"):
        return f"https:{s}"
    if s.startswith("/"):
        return f"{YMGAL_BASE_URL}{s}"
    return s


def _extract_extension_names(raw: Any) -> list[str]:
    names: list[str] = []
    if not raw:
        return names
    if isinstance(raw, str):
        for p in re.split(r"[,，/、\n]+", raw):
            s = p.strip()
            if s and s not in names:
                names.append(s)
        return names
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                n = str(item.get("name") or item.get("value") or "").strip()
            else:
                n = str(item or "").strip()
            if n and n not in names:
                names.append(n)
    return names


class YMGalScraper(BaseScraper):
    """YMGal（月幕 Galgame）开放平台刮削器：支持 OAuth2 凭证 + 公开只读兜底与 GA{id} 直查"""

    source_id = "ymgal"
    source_name = "YMGAL"
    display_name = "YMGal 月幕 Galgame"
    requires_api_key = False
    categories = ("galgame",)
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

    def _effective_credentials(self) -> tuple[str, str]:
        if self.client_id and self.client_secret:
            return self.client_id, self.client_secret
        return YMGAL_PUBLIC_CLIENT_ID, YMGAL_PUBLIC_CLIENT_SECRET

    def parse_direct_id(self, query: str) -> str | None:
        raw = (query or "").strip()
        if not raw:
            return None
        m = _YMGAL_URL_RE.search(raw)
        if m:
            return f"GA{m.group(1)}"
        m2 = _YMGAL_ID_RE.match(raw)
        if m2:
            return f"GA{m2.group(1)}"
        m3 = _YMGAL_PREFIX_RE.match(raw)
        if m3:
            return f"GA{m3.group(1)}"
        return None

    @staticmethod
    def _numeric_gid(source_id: str) -> str:
        raw = (source_id or "").strip()
        m = re.search(r"(\d+)", raw)
        return m.group(1) if m else ""

    async def _get_access_token(self, client, *, force_refresh: bool = False) -> str:
        cid, csec = self._effective_credentials()
        cache_key = (cid, csec)
        now = time.monotonic()
        if not force_refresh and cache_key in _TOKEN_CACHE:
            token, exp = _TOKEN_CACHE[cache_key]
            if token and exp > now + 30:
                return token

        params = {
            "grant_type": "client_credentials",
            "client_id": cid,
            "client_secret": csec,
            "scope": "public",
        }
        try:
            resp = await client.get(YMGAL_OAUTH_URL, params=params)
            if resp.status_code != 200:
                resp = await client.post(YMGAL_OAUTH_URL, params=params)
            if resp.status_code == 200:
                data = resp.json()
                token = str(data.get("access_token") or "").strip()
                expires_in = int(data.get("expires_in") or 3600)
                if token:
                    _TOKEN_CACHE[cache_key] = (token, now + max(60, expires_in - 60))
                    return token
        except Exception as exc:
            logger.debug("YMGal OAuth token fetch failed: %s", exc)
        return ""

    async def _authorized_get(self, client, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        token = await self._get_access_token(client, force_refresh=False)
        headers: dict[str, str] = {"version": "1", "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        resp = await client.get(url, params=params, headers=headers)
        if resp.status_code == 401 and token:
            # 遵照官方建议：遇到 Token 失效拒绝时即时刷新重试一次
            token = await self._get_access_token(client, force_refresh=True)
            if token:
                headers["Authorization"] = f"Bearer {token}"
                resp = await client.get(url, params=params, headers=headers)

        if resp.status_code != 200:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def _parse_search_entry(self, entry: dict[str, Any]) -> ScraperSearchResult:
        raw_id = str(entry.get("id") or entry.get("gid") or "").strip()
        num_id = self._numeric_gid(raw_id)
        ga_id = f"GA{num_id}" if num_id else raw_id

        zh_name = str(entry.get("chineseName") or "").strip()
        orig_name = str(entry.get("name") or "").strip()
        title = zh_name or orig_name or ga_id
        original_title = orig_name if (zh_name and orig_name and orig_name != zh_name) else ""

        aliases = [
            a
            for a in _extract_extension_names(entry.get("extensionName") or entry.get("aliases"))
            if a != title and a != original_title
        ]

        developers = split_entity_names(
            entry.get("orgName") or entry.get("developerName") or entry.get("developer") or ""
        )
        release_date = str(entry.get("releaseDate") or "").strip()
        cover_url = _normalize_image_url(entry.get("mainImg") or entry.get("cover") or "")
        is_nsfw = bool(entry.get("restricted", entry.get("nsfw", False)))

        raw_tags = entry.get("tags") or []
        tag_list = [
            str(t.get("name") if isinstance(t, dict) else t)
            for t in raw_tags
            if t
        ]
        tags = clean_scraped_tags(
            tag_list,
            title=title,
            sub_title=original_title,
            developer=", ".join(developers),
        )

        return ScraperSearchResult(
            source=self.source_id,
            source_id=ga_id,
            source_url=f"{YMGAL_BASE_URL}/{ga_id}" if ga_id else YMGAL_BASE_URL,
            title=title,
            original_title=original_title,
            aliases=aliases,
            developers=developers,
            publishers=[],
            release_date=release_date,
            description=_clean_text(entry.get("introduction") or ""),
            tags=tags,
            cover_url=cover_url if (self.allow_nsfw or not is_nsfw) else "",
            background_url="",
            external_ids=normalize_external_ids({"ymgal": ga_id}),
            is_nsfw=is_nsfw,
        )

    def _parse_archive_detail(self, data: dict[str, Any], fallback_num_id: str) -> ScraperGameDetail | None:
        game = data.get("game") if isinstance(data.get("game"), dict) else data
        if not isinstance(game, dict) or not (game.get("name") or game.get("chineseName") or game.get("gid")):
            return None

        num_id = self._numeric_gid(str(game.get("gid") or game.get("id") or fallback_num_id))
        ga_id = f"GA{num_id}" if num_id else fallback_num_id

        zh_name = str(game.get("chineseName") or "").strip()
        orig_name = str(game.get("name") or "").strip()
        title = zh_name or orig_name or ga_id
        original_title = orig_name if (zh_name and orig_name and orig_name != zh_name) else ""

        aliases = [
            a
            for a in _extract_extension_names(game.get("extensionName"))
            if a != title and a != original_title
        ]

        # 从 oidMapping 或 orgName 中解析开发商
        developers: list[str] = []
        oid_mapping = data.get("oidMapping") if isinstance(data.get("oidMapping"), dict) else {}
        dev_id = str(game.get("developerId") or "").strip()
        if dev_id and dev_id in oid_mapping and isinstance(oid_mapping[dev_id], dict):
            org = oid_mapping[dev_id]
            org_name = str(org.get("chineseName") or org.get("name") or "").strip()
            if org_name:
                developers.append(org_name)
        if not developers:
            developers = split_entity_names(game.get("orgName") or game.get("developerName") or "")

        # 从 releases 中补充发行商或更准确发售日
        publishers: list[str] = []
        release_date = str(game.get("releaseDate") or "").strip()
        for rel in game.get("releases") or []:
            if not isinstance(rel, dict):
                continue
            if not release_date and rel.get("releaseDate"):
                release_date = str(rel["releaseDate"]).strip()
            pub_name = str(rel.get("publisherName") or "").strip()
            if pub_name and pub_name not in publishers:
                publishers.append(pub_name)

        raw_tags = game.get("tags") or []
        tag_list: list[str] = []
        for t in raw_tags:
            if isinstance(t, dict) and (t.get("name") or t.get("chineseName")):
                tag_list.append(str(t.get("chineseName") or t.get("name")))
            elif isinstance(t, str) and t.strip():
                tag_list.append(t.strip())
        if game.get("haveChinese"):
            tag_list.append("有中文")

        tags = clean_scraped_tags(
            tag_list,
            title=title,
            sub_title=original_title,
            developer=", ".join(developers),
            publisher=", ".join(publishers),
        )

        # 解析外站链接收敛 external_ids
        ext: dict[str, Any] = {"ymgal": ga_id}
        for site in game.get("websites") or []:
            link = str(site.get("link") if isinstance(site, dict) else site or "")
            if not link:
                continue
            if "steam" not in ext:
                m = _STEAM_APP_RE.search(link)
                if m:
                    ext["steam"] = m.group(1)
            if "vndb" not in ext:
                m = _VNDB_ID_RE.search(link)
                if m:
                    ext["vndb"] = f"v{m.group(1)}"
            if "bangumi" not in ext:
                m = _BGM_ID_RE.search(link)
                if m:
                    ext["bangumi"] = m.group(1)
            if "dlsite" not in ext:
                m = _DLSITE_CODE_RE.search(link)
                if m:
                    ext["dlsite"] = m.group(1).upper()

        is_nsfw = bool(game.get("restricted", False))
        cover_url = _normalize_image_url(game.get("mainImg") or "")
        if not self.allow_nsfw and is_nsfw:
            cover_url = ""

        return ScraperGameDetail(
            source=self.source_id,
            source_id=ga_id,
            source_url=f"{YMGAL_BASE_URL}/{ga_id}",
            title=title,
            original_title=original_title,
            aliases=aliases,
            developers=developers,
            publishers=publishers,
            release_date=release_date,
            description=_clean_text(game.get("introduction") or ""),
            tags=tags,
            cover_url=cover_url,
            background_url="",
            external_ids=normalize_external_ids(ext),
            is_nsfw=is_nsfw,
        )

    async def _public_html_detail_fallback(self, client, ga_id: str) -> ScraperGameDetail | None:
        try:
            resp = await client.get(
                f"{YMGAL_BASE_URL}/{ga_id}",
                headers={"Accept": "text/html,application/xhtml+xml"},
            )
            if resp.status_code != 200 or not resp.text:
                return None
            metas = {
                m.group(1).strip().lower(): html.unescape(m.group(2).strip())
                for m in _META_TAG_RE.finditer(resp.text)
            }
            title = metas.get("og:title") or ""
            title = re.sub(r"\s*[-|–—]\s*月幕.*$", "", title).strip()
            if not title:
                return None
            return ScraperGameDetail(
                source=self.source_id,
                source_id=ga_id,
                source_url=f"{YMGAL_BASE_URL}/{ga_id}",
                title=title,
                description=_clean_text(metas.get("og:description") or metas.get("description") or ""),
                cover_url=_normalize_image_url(metas.get("og:image") or ""),
                external_ids=normalize_external_ids({"ymgal": ga_id}),
            )
        except Exception:
            return None

    async def search(self, query: str, limit: int = 8) -> list[ScraperSearchResult]:
        q = (query or "").strip()
        if not q:
            return []

        direct_id = self.parse_direct_id(q)
        if direct_id:
            detail = await self.get_detail(direct_id)
            return [detail] if detail else []

        capped = max(1, min(limit, 25))
        params = {
            "mode": "list",
            "keyword": q[:95],
            "pageNum": 1,
            "pageSize": capped,
        }
        try:
            async with self._build_client() as client:
                payload = await self._authorized_get(client, YMGAL_SEARCH_URL, params)
                if not payload:
                    return []
                data = payload.get("data")
                raw_list: list[Any] = []
                if isinstance(data, dict):
                    raw_list = data.get("result") or data.get("list") or data.get("records") or []
                elif isinstance(data, list):
                    raw_list = data

                results: list[ScraperSearchResult] = []
                for item in raw_list[:capped]:
                    if not isinstance(item, dict):
                        continue
                    parsed = self._parse_search_entry(item)
                    if not self.allow_nsfw and parsed.is_nsfw:
                        continue
                    results.append(parsed)
                return results
        except Exception as exc:
            logger.warning("YMGal search failed for %r: %s", q, exc)
            return []

    async def get_detail(self, source_id: str) -> ScraperGameDetail | None:
        raw_id = (source_id or "").strip()
        parsed_id = self.parse_direct_id(raw_id) or raw_id
        num_id = self._numeric_gid(parsed_id)
        if not num_id:
            return None
        ga_id = f"GA{num_id}"

        try:
            async with self._build_client() as client:
                payload = await self._authorized_get(client, YMGAL_ARCHIVE_URL, {"gid": num_id})
                if payload and isinstance(payload.get("data"), dict):
                    detail = self._parse_archive_detail(payload["data"], num_id)
                    if detail:
                        return detail
                return await self._public_html_detail_fallback(client, ga_id)
        except Exception as exc:
            logger.warning("YMGal get_detail failed for %r: %s", ga_id, exc)
            return None

    async def test_connection(self, timeout: float = 6.0) -> dict[str, Any]:
        t0 = time.monotonic()
        has_custom = bool(self.client_id and self.client_secret)
        try:
            async with self._build_client(timeout=timeout) as client:
                cid, csec = self._effective_credentials()
                params = {
                    "grant_type": "client_credentials",
                    "client_id": cid,
                    "client_secret": csec,
                    "scope": "public",
                }
                oauth_resp = await client.get(YMGAL_OAUTH_URL, params=params)
                if oauth_resp.status_code != 200:
                    oauth_resp = await client.post(YMGAL_OAUTH_URL, params=params)
                elapsed = int((time.monotonic() - t0) * 1000)

                if oauth_resp.status_code in (400, 401, 403):
                    return {
                        "ok": False,
                        "source": self.source_id,
                        "latency_ms": elapsed,
                        "detail": (
                            "Client ID 或 Client Secret 无效"
                            if has_custom
                            else f"公开只读通道鉴权失败 (HTTP {oauth_resp.status_code})"
                        ),
                    }
                if oauth_resp.status_code != 200:
                    return {
                        "ok": False,
                        "source": self.source_id,
                        "latency_ms": elapsed,
                        "detail": f"鉴权接口返回异常 (HTTP {oauth_resp.status_code})",
                    }

                token = str((oauth_resp.json() or {}).get("access_token") or "").strip()
                if not token:
                    return {
                        "ok": False,
                        "source": self.source_id,
                        "latency_ms": elapsed,
                        "detail": "未获取到有效的 OAuth Token",
                    }

                resp = await client.get(
                    YMGAL_SEARCH_URL,
                    params={"mode": "list", "keyword": "CLANNAD", "pageNum": 1, "pageSize": 1},
                    headers={"version": "1", "Accept": "application/json", "Authorization": f"Bearer {token}"},
                )
                elapsed = int((time.monotonic() - t0) * 1000)
                if resp.status_code in (401, 403):
                    return {
                        "ok": False,
                        "source": self.source_id,
                        "latency_ms": elapsed,
                        "detail": f"接口鉴权被拒 (HTTP {resp.status_code})",
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
                data = resp.json()
                raw_data = data.get("data") if isinstance(data, dict) else None
                raw_list = (
                    (raw_data.get("result") or raw_data.get("list") or [])
                    if isinstance(raw_data, dict)
                    else (raw_data if isinstance(raw_data, list) else [])
                )
                suffix = "，已认证" if has_custom else ""
                return {
                    "ok": True,
                    "source": self.source_id,
                    "latency_ms": elapsed,
                    "sample_count": len(raw_list),
                    "detail": f"连接正常 ({elapsed}ms{suffix})",
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
