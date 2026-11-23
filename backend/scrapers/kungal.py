from __future__ import annotations

import html
import json
import logging
import re
import time
from typing import Any
from urllib.parse import urljoin

import httpx

from backend.scrapers.base import (
    BaseScraper,
    ScraperGameDetail,
    ScraperSearchResult,
    clean_scraped_tags,
    normalize_external_ids,
    split_entity_names,
)

logger = logging.getLogger("tsumugi.scrapers.kungal")

DEFAULT_KUNGAL_BASE_URL = "https://www.kungal.com"

_KUNGAL_URL_RE = re.compile(
    r"https?://(?:www\.)?kungal\.(?:com|org)/(?:zh-cn/|en-us/|ja-jp/)?galgame/(\d+)",
    re.IGNORECASE,
)
_KUNGAL_PREFIX_RE = re.compile(
    r"^(?:kungal|kun)[:/#\s-]?(?:galgame/)?(\d+)$",
    re.IGNORECASE,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_META_TAG_RE = re.compile(
    r'<meta\s+[^>]*?(?:property|name)=["\']([^"\']+)["\'][^>]*?content=["\']([^"\']*)["\']',
    re.IGNORECASE,
)
_META_TAG_REV_RE = re.compile(
    r'<meta\s+[^>]*?content=["\']([^"\']*)["\'][^>]*?(?:property|name)=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_VNDB_ID_RE = re.compile(r"\bv(\d+)\b", re.IGNORECASE)
_BGM_URL_RE = re.compile(r"(?:bgm\.tv|bangumi\.tv)/subject/(\d+)", re.IGNORECASE)
_STEAM_URL_RE = re.compile(r"store\.steampowered\.com/app/(\d+)", re.IGNORECASE)
_DLSITE_CODE_RE = re.compile(r"\b((?:RJ|VJ|BJ)\d{4,10})\b", re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})")


def _clean_text(raw: Any) -> str:
    if not raw:
        return ""
    text = str(raw)
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _normalize_date(raw: Any) -> str:
    if not raw:
        return ""
    if isinstance(raw, (int, float)):
        # 毫秒或秒级时间戳
        ts = float(raw)
        if ts > 1e12:
            ts /= 1000.0
        if ts > 0:
            try:
                return time.strftime("%Y-%m-%d", time.gmtime(ts))
            except Exception:
                return ""
    s = str(raw).strip()
    m = _DATE_RE.search(s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s[:10] if len(s) >= 10 and s[4] == "-" else s


def _pick_localized(val: Any) -> tuple[str, str, list[str]]:
    """
    从 Kungal 多语言对象（如 {"zh-cn": "...", "ja-jp": "...", "en-us": "..."}）
    提取 (中文/主标题, 日文原名, 其余别名列表)。
    """
    if isinstance(val, str):
        s = val.strip()
        return s, "", []
    if not isinstance(val, dict):
        return "", "", []

    norm = {str(k).strip().lower().replace("_", "-"): str(v).strip() for k, v in val.items() if v}
    zh = norm.get("zh-cn") or norm.get("zh-hans") or norm.get("zh-tw") or norm.get("zh") or ""
    ja = norm.get("ja-jp") or norm.get("ja") or norm.get("jp") or ""
    en = norm.get("en-us") or norm.get("en") or ""

    primary = zh or ja or en or next(iter(norm.values()), "")
    original = ja if (ja and ja != primary) else (en if (en and en != primary) else "")
    aliases: list[str] = []
    for cand in norm.values():
        if cand and cand != primary and cand != original and cand not in aliases:
            aliases.append(cand)
    return primary, original, aliases


def _pick_localized_text(val: Any) -> str:
    if isinstance(val, str):
        return _clean_text(val)
    if isinstance(val, dict):
        norm = {str(k).strip().lower().replace("_", "-"): v for k, v in val.items() if v}
        for key in ("zh-cn", "zh-hans", "zh-tw", "zh", "en-us", "en", "ja-jp", "ja"):
            if norm.get(key):
                return _clean_text(norm[key])
        for v in norm.values():
            cleaned = _clean_text(v)
            if cleaned:
                return cleaned
    return ""


class KungalScraper(BaseScraper):
    """Kungal（鲲Gal）刮削器：支持关键词搜索、kungal.com/galgame/{id} 直查与自定义 API Base URL"""

    source_id = "kungal"
    source_name = "KUNGAL"
    display_name = "Kungal 鲲Gal"
    requires_api_key = False
    categories = ("galgame",)
    default_timeout = 8.0

    def __init__(
        self,
        proxy_url: str = "",
        api_key: str = "",
        allow_nsfw: bool = True,
        base_url: str = DEFAULT_KUNGAL_BASE_URL,
        custom_headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> None:
        super().__init__(
            proxy_url=proxy_url,
            api_key=api_key,
            allow_nsfw=allow_nsfw,
            timeout=timeout,
        )
        cleaned_base = (base_url or "").strip().rstrip("/")
        self.base_url = cleaned_base or DEFAULT_KUNGAL_BASE_URL
        self.custom_headers = dict(custom_headers or {})

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{self.base_url}/",
            "Origin": self.base_url,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.custom_headers:
            headers.update(self.custom_headers)
        return headers

    def parse_direct_id(self, query: str) -> str | None:
        raw = (query or "").strip()
        if not raw:
            return None
        m = _KUNGAL_URL_RE.search(raw)
        if m:
            return m.group(1)
        m2 = _KUNGAL_PREFIX_RE.match(raw)
        if m2:
            return m2.group(1)
        # 兼容用户自定义的域名，例如 https://my-kungal.example/galgame/12345
        if self.base_url and raw.lower().startswith(self.base_url.lower()):
            m_custom = re.search(r"/galgame/(\d+)", raw, re.IGNORECASE)
            if m_custom:
                return m_custom.group(1)
        return None

    def _resolve_url(self, raw: Any) -> str:
        s = str(raw or "").strip()
        if not s:
            return ""
        if s.startswith("//"):
            return f"https:{s}"
        if s.startswith(("http://", "https://")):
            return s
        return urljoin(f"{self.base_url}/", s.lstrip("/"))

    def _parse_entry(self, entry: dict[str, Any], *, as_detail: bool = False) -> ScraperGameDetail:
        gid = str(entry.get("gid") or entry.get("id") or entry.get("galgame_id") or "").strip()

        # 标题、原名与别名提取
        name_field = entry.get("name") or entry.get("title")
        title, original_title, loc_aliases = _pick_localized(name_field)
        if not title:
            title = str(
                entry.get("name_cn")
                or entry.get("chinese_name")
                or entry.get("title")
                or gid
            ).strip()
        if not original_title:
            orig_cand = str(
                entry.get("original_name")
                or entry.get("originalName")
                or entry.get("ja_name")
                or entry.get("alttitle")
                or ""
            ).strip()
            if orig_cand and orig_cand != title:
                original_title = orig_cand

        aliases: list[str] = list(loc_aliases)
        raw_aliases = entry.get("alias") or entry.get("aliases") or []
        if isinstance(raw_aliases, str):
            raw_aliases = [a.strip() for a in re.split(r"[,，/、\n]+", raw_aliases) if a.strip()]
        if isinstance(raw_aliases, list):
            for a in raw_aliases:
                s = str(a.get("name") if isinstance(a, dict) else a).strip()
                if s and s != title and s != original_title and s not in aliases:
                    aliases.append(s)

        # 开发商 / 发行商
        dev_raw = (
            entry.get("developers")
            or entry.get("developer")
            or entry.get("brand")
            or entry.get("studio")
            or entry.get("company")
        )
        if isinstance(dev_raw, list):
            developers = split_entity_names(
                [str(d.get("name") if isinstance(d, dict) else d) for d in dev_raw]
            )
        else:
            developers = split_entity_names(str(dev_raw or ""))

        pub_raw = entry.get("publishers") or entry.get("publisher")
        if isinstance(pub_raw, list):
            publishers = split_entity_names(
                [str(p.get("name") if isinstance(p, dict) else p) for p in pub_raw]
            )
        else:
            publishers = split_entity_names(str(pub_raw or ""))

        release_date = _normalize_date(
            entry.get("release_date")
            or entry.get("releaseDate")
            or entry.get("released")
            or entry.get("published_at")
            or entry.get("publish_date")
        )

        description = _pick_localized_text(
            entry.get("introduction")
            or entry.get("description")
            or entry.get("summary")
            or ""
        )

        # 标签提取与清洗
        raw_tags = entry.get("tags") or entry.get("type") or []
        tag_names: list[str] = []
        if isinstance(raw_tags, list):
            for t in raw_tags:
                if isinstance(t, dict) and t.get("name"):
                    tag_names.append(str(t["name"]))
                elif isinstance(t, str) and t.strip():
                    tag_names.append(t.strip())
        cleaned_tags = clean_scraped_tags(
            tag_names,
            title=title,
            sub_title=original_title,
            developer=", ".join(developers),
            publisher=", ".join(publishers),
        )

        # 图片资源
        cover_raw = (
            entry.get("cover")
            or entry.get("cover_url")
            or entry.get("banner")
            or entry.get("image")
            or ""
        )
        bg_raw = entry.get("banner") or entry.get("background") or entry.get("hero") or ""
        cover_url = self._resolve_url(cover_raw)
        background_url = self._resolve_url(bg_raw) if bg_raw else ""

        screenshots: list[str] = []
        for ss in entry.get("screenshots") or entry.get("images") or []:
            u = self._resolve_url(ss.get("url") if isinstance(ss, dict) else ss)
            if u and u not in screenshots:
                screenshots.append(u)

        # 外部关联 ID 提取
        ext: dict[str, Any] = {}
        if gid:
            ext["kungal"] = gid
        vndb_raw = str(entry.get("vndb_id") or entry.get("vndbId") or "").strip()
        if vndb_raw:
            ext["vndb"] = vndb_raw
        bgm_raw = str(entry.get("bangumi_id") or entry.get("bgm_id") or "").strip()
        if bgm_raw:
            ext["bangumi"] = bgm_raw
        steam_raw = str(entry.get("steam_id") or entry.get("steam_appid") or "").strip()
        if steam_raw:
            ext["steam"] = steam_raw
        dlsite_raw = str(entry.get("dlsite_id") or "").strip()
        if dlsite_raw:
            ext["dlsite"] = dlsite_raw

        # 从外链数组或正文中顺带提取外站 ID
        for link_item in entry.get("links") or entry.get("resources") or []:
            u = str(link_item.get("url") if isinstance(link_item, dict) else link_item or "")
            if not ext.get("vndb"):
                mv = _VNDB_ID_RE.search(u)
                if mv and "vndb" in u.lower():
                    ext["vndb"] = f"v{mv.group(1)}"
            if not ext.get("bangumi"):
                mb = _BGM_URL_RE.search(u)
                if mb:
                    ext["bangumi"] = mb.group(1)
            if not ext.get("steam"):
                ms = _STEAM_URL_RE.search(u)
                if ms:
                    ext["steam"] = ms.group(1)
            if not ext.get("dlsite"):
                md = _DLSITE_CODE_RE.search(u)
                if md:
                    ext["dlsite"] = md.group(1).upper()

        is_nsfw = bool(entry.get("is_nsfw", entry.get("nsfw", entry.get("r18", False))))
        if not self.allow_nsfw and is_nsfw:
            cover_url = ""
            background_url = ""

        model_cls = ScraperGameDetail if as_detail else ScraperSearchResult
        return model_cls(
            source=self.source_id,
            source_id=gid,
            source_url=f"{self.base_url}/galgame/{gid}" if gid else self.base_url,
            title=title or gid,
            original_title=original_title,
            aliases=aliases,
            developers=developers,
            publishers=publishers,
            release_date=release_date,
            description=description,
            tags=cleaned_tags,
            cover_url=cover_url,
            background_url=background_url,
            external_ids=normalize_external_ids(ext),
            is_nsfw=is_nsfw,
            screenshots=screenshots[:12],
        )

    @staticmethod
    def _extract_list_from_payload(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if not isinstance(payload, dict):
            return []
        data = payload.get("data")
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            for key in ("galgames", "items", "results", "list", "data"):
                candidate = data.get(key)
                if isinstance(candidate, list):
                    return [x for x in candidate if isinstance(x, dict)]
        for key in ("galgames", "items", "results", "list"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return [x for x in candidate if isinstance(x, dict)]
        return []

    @staticmethod
    def _extract_object_from_payload(payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if isinstance(data, dict):
            if isinstance(data.get("galgame"), dict):
                return data["galgame"]
            return data
        if any(k in payload for k in ("gid", "id", "name", "title", "introduction")):
            return payload
        return None

    def _parse_html_fallback(self, html_text: str, gid: str) -> ScraperGameDetail | None:
        metas: dict[str, str] = {}
        for m in _META_TAG_RE.finditer(html_text):
            metas[m.group(1).strip().lower()] = html.unescape(m.group(2).strip())
        for m in _META_TAG_REV_RE.finditer(html_text):
            metas.setdefault(m.group(2).strip().lower(), html.unescape(m.group(1).strip()))

        title = metas.get("og:title") or metas.get("twitter:title") or ""
        if not title:
            tm = _TITLE_TAG_RE.search(html_text)
            if tm:
                title = html.unescape(tm.group(1).strip())
        title = re.sub(r"\s*[-|–—]\s*(?:KUN|Kungal|鲲Gal).*$", "", title, flags=re.IGNORECASE).strip()
        if not title:
            return None

        desc = metas.get("og:description") or metas.get("description") or ""
        img = self._resolve_url(metas.get("og:image") or metas.get("twitter:image") or "")

        ext: dict[str, str] = {"kungal": gid}
        mv = re.search(r"vndb\.org/v(\d+)", html_text, re.IGNORECASE)
        if mv:
            ext["vndb"] = f"v{mv.group(1)}"

        return ScraperGameDetail(
            source=self.source_id,
            source_id=gid,
            source_url=f"{self.base_url}/galgame/{gid}",
            title=title,
            description=_clean_text(desc),
            cover_url=img,
            background_url=img,
            external_ids=normalize_external_ids(ext),
        )

    async def search(self, query: str, limit: int = 8) -> list[ScraperSearchResult]:
        q = (query or "").strip()
        if not q:
            return []

        direct_id = self.parse_direct_id(q)
        if direct_id:
            detail = await self.get_detail(direct_id)
            return [detail] if detail else []

        capped = max(1, min(limit, 25))
        candidate_requests: list[tuple[str, dict[str, Any]]] = [
            (
                f"{self.base_url}/api/galgame",
                {
                    "keywords": q,
                    "page": 1,
                    "limit": capped,
                    "sortField": "time",
                    "sortOrder": "desc",
                },
            ),
            (
                f"{self.base_url}/api/galgame/search",
                {"keywords": q, "keyword": q, "page": 1, "limit": capped},
            ),
            (
                f"{self.base_url}/api/search",
                {"keywords": q, "type": "galgame", "page": 1, "limit": capped},
            ),
        ]

        async with self._build_client(headers=self._headers()) as client:
            for url, params in candidate_requests:
                try:
                    resp = await client.get(url, params=params)
                    if resp.status_code != 200:
                        continue
                    ctype = (resp.headers.get("content-type") or "").lower()
                    if "json" not in ctype:
                        continue
                    payload = resp.json()
                    raw_items = self._extract_list_from_payload(payload)
                    if raw_items:
                        results: list[ScraperSearchResult] = []
                        for item in raw_items[:capped]:
                            parsed = self._parse_entry(item, as_detail=False)
                            if not self.allow_nsfw and parsed.is_nsfw:
                                continue
                            results.append(parsed)
                        return results
                except Exception as exc:
                    logger.debug("Kungal search endpoint %s failed for %r: %s", url, q, exc)
                    continue

        return []

    async def get_detail(self, source_id: str) -> ScraperGameDetail | None:
        raw_id = (source_id or "").strip()
        parsed_id = self.parse_direct_id(raw_id) or raw_id
        gid = re.sub(r"[^0-9]", "", parsed_id) if parsed_id else ""
        if not gid:
            return None

        api_paths = (
            f"{self.base_url}/api/galgame/{gid}",
            f"{self.base_url}/api/galgame/detail/{gid}",
        )
        async with self._build_client(headers=self._headers()) as client:
            for url in api_paths:
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    ctype = (resp.headers.get("content-type") or "").lower()
                    if "json" not in ctype:
                        continue
                    entry = self._extract_object_from_payload(resp.json())
                    if entry:
                        if not entry.get("gid") and not entry.get("id"):
                            entry = {**entry, "gid": gid}
                        return self._parse_entry(entry, as_detail=True)
                except Exception as exc:
                    logger.debug("Kungal detail API %s failed: %s", url, exc)

            # HTML 页面兜底解析（支持链接直查在 API 变更时仍可用）
            try:
                page_url = f"{self.base_url}/galgame/{gid}"
                resp = await client.get(page_url, headers={"Accept": "text/html,application/xhtml+xml"})
                if resp.status_code == 200 and resp.text:
                    # 尝试解析 JSON-LD
                    for m in re.finditer(
                        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                        resp.text,
                        re.IGNORECASE | re.DOTALL,
                    ):
                        try:
                            ld = json.loads(m.group(1))
                            if isinstance(ld, dict) and ld.get("name"):
                                return self._parse_entry(
                                    {
                                        "gid": gid,
                                        "name": ld.get("name"),
                                        "description": ld.get("description", ""),
                                        "cover": ld.get("image", ""),
                                        "release_date": ld.get("datePublished", ""),
                                    },
                                    as_detail=True,
                                )
                        except Exception:
                            continue
                    return self._parse_html_fallback(resp.text, gid)
            except Exception as exc:
                logger.debug("Kungal HTML fallback failed for %s: %s", gid, exc)

        return None

    async def test_connection(self, timeout: float = 6.0) -> dict[str, Any]:
        t0 = time.monotonic()
        probe_endpoints = (
            (f"{self.base_url}/api/galgame", {"keywords": "CLANNAD", "page": 1, "limit": 1}),
            (f"{self.base_url}/api/galgame/search", {"keywords": "CLANNAD", "page": 1, "limit": 1}),
        )
        last_status: int | None = None
        try:
            async with self._build_client(headers=self._headers(), timeout=timeout) as client:
                for url, params in probe_endpoints:
                    resp = await client.get(url, params=params)
                    last_status = resp.status_code
                    elapsed = int((time.monotonic() - t0) * 1000)
                    if resp.status_code in (401, 403):
                        return {
                            "ok": False,
                            "source": self.source_id,
                            "latency_ms": elapsed,
                            "detail": (
                                f"Token 无效或权限不足 (HTTP {resp.status_code})"
                                if self.api_key
                                else f"站点拒绝访问或触发风控 (HTTP {resp.status_code})"
                            ),
                        }
                    if resp.status_code == 429:
                        return {
                            "ok": False,
                            "source": self.source_id,
                            "latency_ms": elapsed,
                            "detail": "请求过于频繁，触发限流 (HTTP 429)",
                        }
                    if resp.status_code == 200 and "json" in (resp.headers.get("content-type") or "").lower():
                        items = self._extract_list_from_payload(resp.json())
                        return {
                            "ok": True,
                            "source": self.source_id,
                            "latency_ms": elapsed,
                            "sample_count": len(items),
                            "detail": f"连接正常 ({elapsed}ms)",
                        }

                # 兜底检测主站页面可达性（支持链接直查 HTML 兜底）
                home_resp = await client.get(
                    self.base_url,
                    headers={"Accept": "text/html,application/xhtml+xml"},
                )
                elapsed = int((time.monotonic() - t0) * 1000)
                if home_resp.status_code == 200:
                    return {
                        "ok": True,
                        "source": self.source_id,
                        "latency_ms": elapsed,
                        "sample_count": 0,
                        "detail": f"连接正常 ({elapsed}ms，页面直查模式)",
                    }
                return {
                    "ok": False,
                    "source": self.source_id,
                    "latency_ms": elapsed,
                    "detail": f"接口返回异常 (HTTP {home_resp.status_code or last_status})",
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
