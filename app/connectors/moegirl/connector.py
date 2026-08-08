"""萌娘百科 Connector - search/get_detail/normalize 实现

API：官方 MediaWiki API，https://zh.moegirl.org.cn/api.php（国内直连）。

**真实访问的已知情况（实测 2026-08-06，见 ADR 0015）**：
- 必须带浏览器 User-Agent，否则返回 401 action-notallowed；
- `list=search`、`action=parse`、`prop=revisions`（wikitext）、
  `index.php?action=raw` 均被**禁止匿名访问**（返回 Unauthorized）；
- 可用的等价模块：
  - 搜索：`action=query&generator=search&gsrsearch=...`（返回页面数组，
    与 list=search 同一底层搜索，只是响应结构不同）；
  - 详情：`prop=info|pageimages|categories|extracts`（TextExtracts 插件
    提供纯文本简介，无需解析 wikitext）。
- 因此 normalize() 主路径用结构化字段（extract/thumbnail/categories）；
  同时保留 wikitext Infobox 解析兜底（供开放 wikitext 的其它 MediaWiki
  实例/自建 wiki 使用），用真实模板样例测试。

API 文档：https://www.mediawiki.org/wiki/API:Search
             https://www.mediawiki.org/wiki/API:Extracts
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.connectors.base import (
    ConnectorError,
    ConnectorManifest,
    ItemDetail,
    RateLimitError,
    RequestCache,
    SearchResult,
    TokenBucket,
    http_get,
    load_manifest,
)

_MANIFEST_PATH = Path(__file__).parent / "manifest.json"

# 萌娘百科要求浏览器 UA，否则 401（见模块 docstring）
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 明显是"维护类"的分类（页面管理用，不是内容标签），入库时过滤。
# 用较精确的片段，避免误伤正常属性标签（如"双马尾""发饰"）。
_MAINTENANCE_MARKERS = (
    "使用标题替换", "分离袖子", "无法存档的失效链接", "存废", "小作品",
    "待扩充", "无来源", "待审核", "重写", "模板", "保护", "未使用",
    "有争议", "需要", "重定向", "已隐藏",
)


# ---------------------------------------------------------------- wikitext 解析（兜底）

def _find_template_blocks(text: str) -> List[str]:
    """找出所有顶层 {{...}} 模板的 body（处理嵌套大括号）。"""
    blocks = []
    i, n = 0, len(text)
    while i < n:
        start = text.find("{{", i)
        if start == -1:
            break
        depth, j = 2, start + 2
        while j < n and depth > 0:
            if text.startswith("{{", j):
                depth += 2
                j += 2
            elif text.startswith("}}", j):
                depth -= 2
                j += 2
            else:
                j += 1
        if depth == 0:
            blocks.append(text[start + 2: j - 2])
        i = j
    return blocks


def _parse_infobox(wikitext: str) -> Dict[str, str]:
    """从 wikitext 提取第一个 Infobox 模板的字段（| 字段 = 值）。

    复杂模板嵌套不完美解析，作为已知限制（见 ADR 0015）；只取顶层
    竖线字段，首项胜出。
    """
    for body in _find_template_blocks(wikitext):
        lines = body.split("\n")
        first = lines[0].strip() if lines else ""
        if not any(marker in first.lower() for marker in ("infobox", "人物信息", "作品信息", "歌曲信息", "角色信息")):
            continue
        fields: Dict[str, str] = {}
        for line in lines[1:]:
            line = line.strip()
            if not line.startswith("|") or "=" not in line:
                continue
            key, _, val = line[1:].partition("=")
            key = key.strip().lstrip("^").strip()
            val = val.strip()
            if key and key not in fields:
                fields[key] = val
        if fields:
            return fields
    return {}


def _strip_wikitext(text: str) -> str:
    """把 wikitext 片段粗略清洗为纯文本（注释/模板/链接/引用/粗斜体）。"""
    if not text:
        return ""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"\{\{.*?\}\}", "", text, flags=re.S)

    def _link(m: re.Match) -> str:
        inner = m.group(1)
        parts = inner.split("|")
        return parts[-1] if len(parts) > 1 else parts[0]

    text = re.sub(r"\[\[(.*?)\]\]", _link, text, flags=re.S)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", text).strip()


def _first_section(text: str) -> str:
    """取第一个 '==' 标题之前的内容（导言区）。"""
    idx = text.find("==")
    return text[:idx] if idx != -1 else text


# ---------------------------------------------------------------- 数据转换

def _category_to_tag(category_title: str) -> Optional[str]:
    """Category:xxx -> xxx；维护类分类过滤。"""
    name = category_title.split(":", 1)[-1].strip()
    if not name or any(m in name for m in _MAINTENANCE_MARKERS):
        return None
    return name


def _page_to_search_result(page: Dict[str, Any]) -> SearchResult:
    return SearchResult(
        source="moegirl",
        title=page.get("title", ""),
        external_id=str(page.get("pageid", "")),
        description=(page.get("extract") or "")[:300] or None,
        image_url=(page.get("thumbnail") or {}).get("source"),
        raw=page,
    )


def _page_to_detail(page: Dict[str, Any]) -> ItemDetail:
    cats = [
        t for t in (_category_to_tag(c.get("title", "")) for c in (page.get("categories") or []))
        if t
    ]
    return ItemDetail(
        source="moegirl",
        title=page.get("title", ""),
        external_id=str(page.get("pageid", "")),
        description=page.get("extract") or "",
        image_url=(page.get("thumbnail") or {}).get("source"),
        metadata={
            "categories": cats,
            # tags 与 categories 同源（已过滤维护类），供统一"标签"字段消费
            "tags": cats,
            "length": page.get("length"),
            # 页面信息（ADR 0026：MediaWiki 无公开评论/热度数据，仅页面元信息）
            "touched": page.get("touched"),
            "lastrevid": page.get("lastrevid"),
        },
    )


# ---------------------------------------------------------------- Connector

class MoegirlConnector:
    """萌娘百科数据源实现。"""

    name = "moegirl"
    manifest: ConnectorManifest = None

    def __init__(self):
        self.manifest = load_manifest(_MANIFEST_PATH)
        rpm = (self.manifest.rate_limit or {}).get("requests_per_minute", 20)
        self._bucket = TokenBucket(rpm)
        self._cache = RequestCache(namespace=self.name)
        self.proxy_url = None  # 出站代理（可选，registry.apply_settings 注入）

    # ---- HTTP ----
    def _request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self._bucket.acquire()
        try:
            resp = http_get(
                self.manifest.base_url, params=params, timeout=20.0,
                proxy=self.proxy_url, headers={"User-Agent": _UA},
            )
        except httpx.HTTPError as e:
            raise ConnectorError(f"萌娘百科 API 请求失败：{e}") from e
        if resp.status_code == 429:
            raise RateLimitError("萌娘百科 API 限流，请稍后再试。")
        if resp.status_code >= 400:
            raise ConnectorError(f"萌娘百科 API 返回 {resp.status_code}")
        try:
            payload = resp.json()
        except json.JSONDecodeError as e:
            raise ConnectorError("萌娘百科 API 返回非 JSON 数据") from e
        if isinstance(payload, dict) and "error" in payload:
            err = payload["error"]
            info = err.get("info", err.get("code", "未知错误"))
            if err.get("code") == "action-notallowed":
                raise ConnectorError("萌娘百科 API 拒绝访问（需要浏览器 User-Agent 或登录态）")
            raise ConnectorError(f"萌娘百科 API 错误：{info}")
        return payload

    # ---- Protocol 实现 ----
    def search(self, query: str, **filters) -> List[SearchResult]:
        if not query or not query.strip():
            return []
        q = query.strip()
        cache_key = f"search:{q}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return [_page_to_search_result(p) for p in cached]

        # list=search 被禁，用 generator=search（同一底层搜索）。
        # 顺带取 extracts 缩略简介与 pageimages 缩略图，减少后续请求。
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": q,
            "gsrlimit": 10,
            "prop": "pageimages|extracts",
            "piprop": "thumbnail",
            "pithumbsize": 200,
            "exintro": 1,
            "explaintext": 1,
            "format": "json",
        }
        data = self._request(params)
        pages = (data.get("query") or {}).get("pages") or {}
        ordered = sorted(pages.values(), key=lambda p: p.get("index", 0))
        self._cache.set(cache_key, ordered)
        return [_page_to_search_result(p) for p in ordered]

    def get_detail(self, external_id: str) -> ItemDetail:
        cache_key = f"detail:{external_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return _page_to_detail(cached)

        params = {
            "action": "query",
            "pageids": str(external_id),
            "prop": "info|pageimages|categories|extracts",
            "piprop": "thumbnail",
            "pithumbsize": 400,
            "cllimit": 50,
            "exintro": 1,
            "explaintext": 1,
            "format": "json",
        }
        data = self._request(params)
        pages = (data.get("query") or {}).get("pages") or {}
        page = next(iter(pages.values()), None)
        if not page or "missing" in page:
            raise ConnectorError(f"萌娘百科未找到该页面（id={external_id}）")
        self._cache.set(cache_key, page)
        return _page_to_detail(page)

    def normalize(self, raw: dict) -> dict:
        """把外部 API 原始返回转换成本地 Item 的字段字典。

        主路径：结构化字段（extract/thumbnail/categories，来自
        info|pageimages|categories|extracts）。兜底：若 payload 里带
        wikitext（某些 MediaWiki 实例开放），用 Infobox 解析补全
        简介/封面/标签。
        """
        title = raw.get("title", "")
        extract = raw.get("extract") or ""
        thumbnail = (raw.get("thumbnail") or {}).get("source")
        tags = [
            t for t in (_category_to_tag(c.get("title", "")) for c in (raw.get("categories") or []))
            if t
        ]

        wikitext = raw.get("wikitext")
        info = _parse_infobox(wikitext) if wikitext else {}
        if not extract and wikitext:
            # 优先取 Infobox 的"简介"字段（结构更干净），否则退回导言区
            extract = info.get("简介") or _first_section(wikitext)
        if not thumbnail and wikitext:
            thumbnail = info.get("image") or info.get("图片") or info.get("封面") or info.get("imagefile")
        if not tags and wikitext:
            raw_tags = info.get("萌点") or info.get("属性") or ""
            tags = [
                t for t in (_strip_wikitext(x).strip() for x in raw_tags.split("、"))
                if t
            ][:10]

        return {
            "title": title,
            "type": "external_ref",
            "content": _strip_wikitext(extract)[:4000] or "",
            "image_url": thumbnail,
            "source": self.name,
            "external_id": str(raw.get("pageid") or raw.get("external_id") or ""),
            "raw_metadata": raw,
            "tags": tags,
        }


def build_connector() -> MoegirlConnector:
    return MoegirlConnector()
