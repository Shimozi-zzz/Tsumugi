from __future__ import annotations

import html
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

logger = logging.getLogger("tsumugi.scrapers.dlsite")

DLSITE_BASE_URL = "https://www.dlsite.com"
DLSITE_SUGGEST_URL = f"{DLSITE_BASE_URL}/suggest/"

_DLSITE_URL_RE = re.compile(
    r"https?://(?:www\.)?dlsite\.com/[^/\s]+/(?:work|announce)/=/product_id/((?:RJ|VJ|BJ)\d{4,10})(?:\.html)?",
    re.IGNORECASE,
)
_DLSITE_URL_LOOSE_RE = re.compile(
    r"https?://(?:www\.)?dlsite\.com/[^\s]*?\b((?:RJ|VJ|BJ)\d{4,10})\b",
    re.IGNORECASE,
)
_DLSITE_CODE_RE = re.compile(r"^((?:RJ|VJ|BJ)\d{4,10})$", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})")
_META_TAG_RE = re.compile(
    r'<meta\s+[^>]*?(?:property|name)=["\']([^"\']+)["\'][^>]*?content=["\']([^"\']*)["\']',
    re.IGNORECASE,
)
_FSR_WORK_RE = re.compile(
    r'data-product_id=["\']((?:RJ|VJ|BJ)\d{4,10})["\']',
    re.IGNORECASE,
)


def _clean_text(raw: Any) -> str:
    if not raw:
        return ""
    text = str(raw).replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _normalize_url(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if s.startswith("//"):
        return f"https:{s}"
    return s


def _normalize_date(raw: Any) -> str:
    if not raw:
        return ""
    m = _DATE_RE.search(str(raw))
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return str(raw).strip()[:10]


def _sections_for_code(code: str) -> tuple[str, ...]:
    prefix = code[:2].upper()
    if prefix == "VJ":
        return ("pro", "soft")
    if prefix == "BJ":
        return ("books", "comic")
    return ("maniax", "home", "pro")


def _derive_cover_url(code: str) -> str:
    """根据 DLsite 标准图片 CDN 规则构造兜底主图链接"""
    upper = code.upper()
    prefix = upper[:2]
    digits = upper[2:]
    if not digits.isdigit():
        return ""
    bucket_num = ((int(digits) + 999) // 1000) * 1000
    width = max(len(digits), 6)
    bucket = f"{prefix}{bucket_num:0{width}d}"
    cat = "doujin" if prefix == "RJ" else ("professional" if prefix == "VJ" else "books")
    return f"https://img.dlsite.jp/modpub/images2/work/{cat}/{bucket}/{upper}_img_main.jpg"


class DLsiteScraper(BaseScraper):
    """DLsite 刮削器：专精同人/独立视觉小说，支持 RJ/VJ/BJ 作品编号与链接直查及关键词搜索"""

    source_id = "dlsite"
    source_name = "DLSITE"
    display_name = "DLsite"
    requires_api_key = False
    categories = ("galgame",)
    default_timeout = 8.0

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7",
            "Referer": f"{DLSITE_BASE_URL}/",
        }

    def _cookies(self) -> dict[str, str]:
        return {"adultchecked": "1"} if self.allow_nsfw else {}

    def parse_direct_id(self, query: str) -> str | None:
        raw = (query or "").strip()
        if not raw:
            return None
        m = _DLSITE_URL_RE.search(raw)
        if m:
            return m.group(1).upper()
        m_loose = _DLSITE_URL_LOOSE_RE.search(raw)
        if m_loose:
            return m_loose.group(1).upper()
        m_code = _DLSITE_CODE_RE.match(raw)
        if m_code:
            return m_code.group(1).upper()
        return None

    def _parse_product_json(
        self,
        info: dict[str, Any],
        code: str,
        section: str,
    ) -> ScraperGameDetail:
        workno = str(info.get("workno") or info.get("product_id") or code).strip().upper()
        work_name = str(info.get("work_name") or info.get("title") or workno).strip()
        work_name_alt = str(info.get("work_name_masked") or "").strip()

        maker = str(
            info.get("maker_name")
            or info.get("brand_name")
            or info.get("maker_name_en")
            or ""
        ).strip()
        developers = split_entity_names(maker)

        release_date = _normalize_date(
            info.get("regist_date") or info.get("release_date") or info.get("on_sale_date")
        )

        # 简介优先取 intro_s，其次 outline
        description = _clean_text(info.get("intro_s") or info.get("outline") or "")

        # 提取标签（genres 数组或 genre 字段）
        raw_genres = info.get("genres") or info.get("genre") or []
        tag_list: list[str] = []
        if isinstance(raw_genres, list):
            for g in raw_genres:
                if isinstance(g, dict) and g.get("name"):
                    tag_list.append(str(g["name"]))
                elif isinstance(g, str) and g.strip():
                    tag_list.append(g.strip())
        elif isinstance(raw_genres, dict):
            for g in raw_genres.values():
                if isinstance(g, dict) and g.get("name"):
                    tag_list.append(str(g["name"]))

        tags = clean_scraped_tags(
            tag_list,
            title=work_name,
            developer=maker,
        )

        # 封面与预览图
        image_main = info.get("image_main")
        if isinstance(image_main, dict):
            cover_url = _normalize_url(image_main.get("url"))
        else:
            cover_url = _normalize_url(image_main or info.get("work_image"))
        if not cover_url:
            cover_url = _derive_cover_url(workno)

        screenshots: list[str] = []
        raw_samples = info.get("image_samples") or info.get("sample_image_list") or []
        if isinstance(raw_samples, list):
            for s in raw_samples:
                u = _normalize_url(s.get("url") if isinstance(s, dict) else s)
                if u and u not in screenshots:
                    screenshots.append(u)
                if len(screenshots) >= 12:
                    break

        age_cat = info.get("age_category")
        try:
            is_nsfw = int(age_cat) >= 3 if age_cat is not None else (section in ("maniax", "pro", "books"))
        except (TypeError, ValueError):
            is_nsfw = section in ("maniax", "pro", "books")

        if not self.allow_nsfw and is_nsfw:
            cover_url = ""
            screenshots = []

        # 评分（DLsite 0~50 或 0~5，归一化至 0~10）
        rating: float | None = None
        rate_avg = info.get("rate_average_2dp") or info.get("rate_average")
        if rate_avg is not None:
            try:
                val = float(rate_avg)
                if val > 10:
                    val = val / 5.0
                elif val <= 5:
                    val = val * 2.0
                if 0 < val <= 10:
                    rating = round(val, 2)
            except (TypeError, ValueError):
                pass

        aliases: list[str] = []
        if work_name_alt and work_name_alt != work_name:
            aliases.append(work_name_alt)
        series_name = str(info.get("series_name") or "").strip()
        if series_name and series_name != work_name:
            aliases.append(series_name)

        return ScraperGameDetail(
            source=self.source_id,
            source_id=workno,
            source_url=f"{DLSITE_BASE_URL}/{section}/work/=/product_id/{workno}.html",
            title=work_name,
            original_title=work_name,
            aliases=aliases,
            developers=developers,
            publishers=[],
            release_date=release_date,
            description=description,
            tags=tags,
            cover_url=cover_url,
            background_url=screenshots[0] if screenshots else "",
            external_ids=normalize_external_ids({"dlsite": workno}),
            is_nsfw=is_nsfw,
            rating=rating,
            screenshots=screenshots,
        )

    def _parse_html_page(self, html_text: str, code: str, section: str) -> ScraperGameDetail | None:
        metas = {
            m.group(1).strip().lower(): html.unescape(m.group(2).strip())
            for m in _META_TAG_RE.finditer(html_text)
        }
        title = metas.get("og:title") or ""
        title = re.sub(r"\s*\[[^\]]+\]\s*\|\s*DLsite.*$", "", title).strip()
        if not title:
            return None

        maker = ""
        m_maker = re.search(
            r'class="maker_name"[^>]*>.*?<a[^>]*>(.*?)</a>',
            html_text,
            re.IGNORECASE | re.DOTALL,
        )
        if m_maker:
            maker = _clean_text(m_maker.group(1))

        cover_url = _normalize_url(metas.get("og:image") or _derive_cover_url(code))
        is_nsfw = section in ("maniax", "pro", "books")
        return ScraperGameDetail(
            source=self.source_id,
            source_id=code,
            source_url=f"{DLSITE_BASE_URL}/{section}/work/=/product_id/{code}.html",
            title=title,
            original_title=title,
            developers=split_entity_names(maker),
            description=_clean_text(metas.get("og:description") or metas.get("description") or ""),
            cover_url=cover_url if (self.allow_nsfw or not is_nsfw) else "",
            external_ids=normalize_external_ids({"dlsite": code}),
            is_nsfw=is_nsfw,
        )

    async def get_detail(self, source_id: str) -> ScraperGameDetail | None:
        raw = (source_id or "").strip()
        code = self.parse_direct_id(raw) or raw.upper()
        if not _DLSITE_CODE_RE.match(code):
            return None

        sections = _sections_for_code(code)
        async with self._build_client(headers=self._headers(), cookies=self._cookies()) as client:
            # 1. 优先调用 DLsite Product Info JSON 接口（尝试 zh_CN 与 ja_JP）
            for section in sections:
                for locale in ("zh_CN", "ja_JP"):
                    api_url = f"{DLSITE_BASE_URL}/{section}/api/=/product.json"
                    try:
                        resp = await client.get(api_url, params={"workno": code, "locale": locale})
                        if resp.status_code != 200:
                            continue
                        payload = resp.json()
                        info: dict[str, Any] | None = None
                        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
                            info = payload[0]
                        elif isinstance(payload, dict) and (payload.get("work_name") or payload.get("workno")):
                            info = payload
                        if info:
                            return self._parse_product_json(info, code, section)
                    except Exception as exc:
                        logger.debug("DLsite JSON %s (%s) failed for %s: %s", section, locale, code, exc)

            # 2. 页面元数据 HTML 兜底
            for section in sections[:2]:
                page_url = f"{DLSITE_BASE_URL}/{section}/work/=/product_id/{code}.html"
                try:
                    resp = await client.get(page_url)
                    if resp.status_code == 200 and resp.text:
                        parsed = self._parse_html_page(resp.text, code, section)
                        if parsed:
                            return parsed
                except Exception as exc:
                    logger.debug("DLsite HTML fallback failed for %s: %s", code, exc)

        return None

    async def search(self, query: str, limit: int = 8) -> list[ScraperSearchResult]:
        q = (query or "").strip()
        if not q:
            return []

        # 若为 RJ/VJ/BJ 编号或 DLsite 链接，直接拉取精确详情
        direct_code = self.parse_direct_id(q)
        if direct_code:
            detail = await self.get_detail(direct_code)
            return [detail] if detail else []

        capped = max(1, min(limit, 20))
        results: list[ScraperSearchResult] = []
        seen_codes: set[str] = set()

        async with self._build_client(headers=self._headers(), cookies=self._cookies()) as client:
            # 1. DLsite Suggest JSON 检索（响应快、结构化程度高）
            sites = ("adult-jp", "general-jp") if self.allow_nsfw else ("general-jp",)
            for site in sites:
                try:
                    resp = await client.get(
                        DLSITE_SUGGEST_URL,
                        params={
                            "term": q,
                            "site": site,
                            "time": int(time.time() * 1000),
                            "touch": 0,
                        },
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    works = data.get("work") if isinstance(data, dict) else []
                    for w in works or []:
                        if not isinstance(w, dict):
                            continue
                        workno = str(w.get("workno") or "").strip().upper()
                        if not workno or workno in seen_codes or not _DLSITE_CODE_RE.match(workno):
                            continue
                        seen_codes.add(workno)
                        section = _sections_for_code(workno)[0]
                        is_nsfw = site == "adult-jp"
                        title = str(w.get("work_name") or workno).strip()
                        maker = str(w.get("maker_name") or "").strip()
                        work_type = str(w.get("work_type") or "").strip()
                        tags = [work_type] if work_type else []
                        results.append(
                            ScraperSearchResult(
                                source=self.source_id,
                                source_id=workno,
                                source_url=f"{DLSITE_BASE_URL}/{section}/work/=/product_id/{workno}.html",
                                title=title,
                                original_title=title,
                                developers=split_entity_names(maker),
                                tags=tags,
                                cover_url=_derive_cover_url(workno) if (self.allow_nsfw or not is_nsfw) else "",
                                external_ids=normalize_external_ids({"dlsite": workno}),
                                is_nsfw=is_nsfw,
                            )
                        )
                        if len(results) >= capped:
                            return results
                except Exception as exc:
                    logger.debug("DLsite suggest (%s) failed for %r: %s", site, q, exc)

            # 2. 若 Suggest 结果不足，回退到 DLsite 搜索结果页提取作品编号
            if not results:
                section = "maniax" if self.allow_nsfw else "home"
                search_url = (
                    f"{DLSITE_BASE_URL}/{section}/fsr/=/language/jp/keyword/{quote(q)}"
                    f"/order/trend/per_page/{capped}"
                )
                try:
                    resp = await client.get(search_url)
                    if resp.status_code == 200 and resp.text:
                        found_codes: list[str] = []
                        for m in _FSR_WORK_RE.finditer(resp.text):
                            c = m.group(1).upper()
                            if c not in seen_codes:
                                seen_codes.add(c)
                                found_codes.append(c)
                            if len(found_codes) >= min(capped, 5):
                                break
                        for code in found_codes:
                            detail = await self.get_detail(code)
                            if detail:
                                results.append(detail)
                except Exception as exc:
                    logger.debug("DLsite FSR search failed for %r: %s", q, exc)

        return results[:capped]

    async def test_connection(self, timeout: float = 6.0) -> dict[str, Any]:
        t0 = time.monotonic()
        try:
            async with self._build_client(
                headers=self._headers(),
                cookies=self._cookies(),
                timeout=timeout,
            ) as client:
                resp = await client.get(
                    DLSITE_SUGGEST_URL,
                    params={
                        "term": "CLANNAD",
                        "site": "general-jp",
                        "time": int(time.time() * 1000),
                        "touch": 0,
                    },
                )
                elapsed = int((time.monotonic() - t0) * 1000)
                if resp.status_code in (401, 403):
                    return {
                        "ok": False,
                        "source": self.source_id,
                        "latency_ms": elapsed,
                        "detail": f"访问受限或地区拦截 (HTTP {resp.status_code})",
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
                works = data.get("work") if isinstance(data, dict) else []
                return {
                    "ok": True,
                    "source": self.source_id,
                    "latency_ms": elapsed,
                    "sample_count": len(works) if isinstance(works, list) else 0,
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
