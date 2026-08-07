"""VNDB Connector - search/get_detail/normalize（Kana API v2，POST + JSON body 风格）

实测结论（2026-08-06，先实测后实现，见 ADR 0023）：
- api.vndb.org **直连可达**（无需代理；代理配置机制保留，需要时经现有配置）；
- 公开 VN/角色查询**不需要 token**（只做搜索/详情，不做用户列表）；
- 查询是 POST /kana/vn | /kana/character + JSON body：`filters` 数组 + `fields`
  逗号串，**不是** GET + query 参数（区别于 Bangumi/萌娘百科）；
- filters 语法实测：
  - 搜索：`["search","=","STEINS;GATE"]`
  - 详情：`["id","=","v2002"]`（值是字符串，不是数组）
  - 角色按 VN：`["vn","=",["id","=","v2002"]]`（值是**嵌套的 VN filter**）
- 角色字段：`vns.role`（main/primary/side/appears）、`vns.spoiler`、
  `image.url`；角色 API 不含声优（声优在 VN 的 `va` 字段，本轮不取，actors 留空）；
- rating 0-100（本项目统一 0-10 展示，除以 10 保留 1 位）；
- 描述含 BBCode（[b] 等），normalize 前清洗；
- 限流：文档"200 请求/5 分钟 + 1 秒执行/分钟" → 令牌桶 40 rpm。
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List

import httpx

from app.connectors.base import (
    ConnectorError,
    ConnectorManifest,
    ItemDetail,
    RateLimitError,
    RequestCache,
    SearchResult,
    TokenBucket,
    http_post,
    load_manifest,
    normalize_characters,
)

_MANIFEST_PATH = Path(__file__).parent / "manifest.json"

# vns.role → 角色墙 relation（与 Bangumi 的中文 relation 一致）
_ROLE_MAP = {"main": "主角", "primary": "主要角色", "side": "配角", "appears": "登场"}

_BBCODE = re.compile(r"\[/?(?:[a-zA-Z0-9]+)(?:=[^\]]*)?\]")


def _strip_bbcode(text: Any) -> str:
    if not text:
        return ""
    return _BBCODE.sub("", str(text)).strip()


def _vn_rating(vn: Dict[str, Any]):
    rating = vn.get("rating")
    return round(rating / 10, 1) if isinstance(rating, (int, float)) else None


def _vn_to_search_result(vn: Dict[str, Any]) -> SearchResult:
    tags = [t.get("name") for t in (vn.get("tags") or []) if t.get("name")]
    return SearchResult(
        source="vndb",
        title=vn.get("title", ""),
        external_id=str(vn.get("id", "")),
        description=_strip_bbcode(vn.get("description"))[:300] or None,
        image_url=(vn.get("image") or {}).get("url"),
        rating=_vn_rating(vn),
        tags=tags[:8],
        raw=vn,
    )


def _vn_to_detail(vn: Dict[str, Any], characters: List[dict]) -> ItemDetail:
    tags = [t.get("name") for t in (vn.get("tags") or []) if t.get("name")]
    return ItemDetail(
        source="vndb",
        title=vn.get("title", ""),
        external_id=str(vn.get("id", "")),
        description=_strip_bbcode(vn.get("description")) or "",
        image_url=(vn.get("image") or {}).get("url"),
        metadata={
            "alttitle": vn.get("alttitle"),
            "released": vn.get("released"),
            "rating": _vn_rating(vn),
            "tags": tags[:12],
            "developers": [d.get("name") for d in (vn.get("developers") or []) if d.get("name")],
            "characters": characters,
        },
    )


def _characters_to_normalized(chars: Any) -> List[dict]:
    """VNDB 角色 → 角色墙统一结构 {id,name,image_url,relation,summary,actors}。"""
    rows = []
    for c in chars or []:
        if not isinstance(c, dict):
            continue
        vns = c.get("vns") or []
        role = vns[0].get("role") if vns else None
        rows.append({
            "id": c.get("id"),
            "name": c.get("name", ""),
            "image_url": (c.get("image") or {}).get("url"),
            "relation": _ROLE_MAP.get(role, role),
            "summary": _strip_bbcode(c.get("description")),
            "actors": [],  # 角色 API 不含声优（在 VN 的 va 字段），本轮留空
        })
    return normalize_characters(rows)


class VndbConnector:
    """VNDB 数据源实现（POST + JSON body，区别于 GET 风格的其它 Connector）。"""

    name = "vndb"
    manifest: ConnectorManifest = None

    def __init__(self):
        self.manifest = load_manifest(_MANIFEST_PATH)
        rpm = (self.manifest.rate_limit or {}).get("requests_per_minute", 40)
        self._bucket = TokenBucket(rpm)
        self._cache = RequestCache(namespace=self.name)
        self.proxy_url = None  # 出站代理（可选，registry.apply_settings 注入）

    # ---- HTTP（POST + JSON body）----
    def _request(self, endpoint: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self._bucket.acquire()
        url = self.manifest.base_url.rstrip("/") + endpoint
        try:
            resp = http_post(url, json_body=body, timeout=20.0, proxy=self.proxy_url,
                             headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            raise ConnectorError(f"VNDB API 请求失败：{e}") from e
        if resp.status_code == 429:
            raise RateLimitError("VNDB API 限流，请稍后再试。")
        if resp.status_code >= 400:
            raise ConnectorError(f"VNDB API 返回 {resp.status_code}：{resp.text[:120]}")
        try:
            return resp.json()
        except json.JSONDecodeError as e:
            raise ConnectorError("VNDB API 返回非 JSON 数据") from e

    # ---- Protocol 实现 ----
    def search(self, query: str, **filters) -> List[SearchResult]:
        if not query or not query.strip():
            return []
        q = query.strip()
        cache_key = f"search:{q}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return [_vn_to_search_result(v) for v in cached]
        data = self._request("/vn", {
            "filters": ["search", "=", q],
            "fields": "id,title,alttitle,image.url,description,rating,developers.name,released,tags.name",
            "sort": "searchrank",
            "results": 10,
        })
        vns = data.get("results") or []
        self._cache.set(cache_key, vns)
        return [_vn_to_search_result(v) for v in vns]

    def get_detail(self, external_id: str) -> ItemDetail:
        cache_key = f"detail:{external_id}"
        chars_key = f"detail_chars:{external_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return _vn_to_detail(cached, self._cache.get(chars_key) or [])

        data = self._request("/vn", {
            "filters": ["id", "=", external_id],
            "fields": "id,title,alttitle,image.url,description,rating,developers.name,released,tags.name",
        })
        vns = data.get("results") or []
        if not vns:
            raise ConnectorError(f"VNDB 未找到该条目（{external_id}）")
        vn = vns[0]
        self._cache.set(cache_key, vn)

        # 角色：角色数据与 VN 强关联；失败不阻塞详情
        chars: List[dict] = []
        try:
            cdata = self._request("/character", {
                "filters": ["vn", "=", ["id", "=", external_id]],
                "fields": "id,name,image.url,description,vns.role,vns.spoiler,vns.title",
                "results": 50,
            })
            chars = _characters_to_normalized(cdata.get("results") or [])
        except ConnectorError:
            chars = []
        self._cache.set(chars_key, chars)

        return _vn_to_detail(vn, chars)

    def normalize(self, raw: dict) -> dict:
        result = _vn_to_search_result(raw)
        return {
            "title": result.title,
            "type": "external_ref",
            "content": _strip_bbcode(raw.get("description"))[:4000] or "",
            "image_url": result.image_url,
            "source": self.name,
            "external_id": result.external_id,
            "raw_metadata": raw,
            "tags": result.tags,
        }


def build_connector() -> VndbConnector:
    return VndbConnector()
