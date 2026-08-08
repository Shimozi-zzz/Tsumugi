"""Bangumi Connector - search/get_detail/normalize 实现（Phase 3）

API 文档：https://bangumi.github.io/api/
- POST /v0/search/subjects  body: {"keyword": "...", "limit": 20, "filter": {...}}
  （注意：搜索端点是 **POST**，GET 返回 404；经本地代理打通后实测确认）
- GET /v0/subjects/{subject_id}
搜索响应每条 subject 含：id, name, name_cn, summary, images, rating,
tags, date 等。
"""
import httpx
from typing import Any, Dict, List

from app.connectors.base import (
    ConnectorError,
    ConnectorManifest,
    ItemDetail,
    RateLimitError,
    RequestCache,
    SearchResult,
    TokenBucket,
    http_get,
    http_post,
    load_manifest,
    normalize_characters,
)
from app.models import Item

_MANIFEST_PATH = __file__ and (__import__("pathlib").Path(__file__).parent / "manifest.json")

# Bangumi 条目类型：2=动画 3=书籍 4=音乐 6=游戏
TYPE_ANIME = 2
TYPE_GAME = 6


# ---------------------------------------------------------------- 数据转换

def _subject_to_search_result(subject: Dict[str, Any]) -> SearchResult:
    tags = [t.get("name", "") for t in (subject.get("tags") or []) if t.get("name")]
    images = subject.get("images") or {}
    rating = subject.get("rating") or {}
    score = rating.get("score")
    return SearchResult(
        source="bangumi",
        title=subject.get("name_cn") or subject.get("name") or "",
        external_id=str(subject.get("id", "")),
        subtitle=subject.get("name"),
        description=subject.get("summary") or "",
        image_url=images.get("large") or images.get("medium") or images.get("common"),
        rating=float(score) if score is not None else None,
        tags=tags[:8],
        raw=subject,
    )


def _subject_to_detail(subject: Dict[str, Any]) -> ItemDetail:
    rating = subject.get("rating") or {}
    return ItemDetail(
        source="bangumi",
        title=subject.get("name_cn") or subject.get("name") or "",
        external_id=str(subject.get("id", "")),
        description=subject.get("summary") or "",
        image_url=(subject.get("images") or {}).get("large"),
        metadata={
            "original_name": subject.get("name"),
            "date": subject.get("date"),
            "rating": rating.get("score"),  # float，兼容既有 get_public_rating
            # 热度/评分分布替代数据（ADR 0026，实测 v0 公开 API 无评论文本）：
            # rating_info = {rank, total, count:{1..10}, score}
            "rating_info": rating,
            # 收藏人数分布 {wish, collect, doing, on_hold, dropped}
            "collection": subject.get("collection"),
            "tags": [t.get("name") for t in (subject.get("tags") or []) if t.get("name")],
            "type": subject.get("type"),
            "volumes": subject.get("volumes"),
            "eps": subject.get("eps"),
        },
    )


def _characters_to_normalized(chars_data: Any) -> List[dict]:
    """把 /v0/subjects/{id}/characters 返回的角色列表规范化。

    Bangumi 角色结构：{id, name, images:{small/grid/large/medium},
    relation, summary, actors:[{id,name,...}]}。先抽出 image_url 再走
    base.normalize_characters 统一字段（见 ADR 0016）。
    """
    rows = []
    for c in chars_data or []:
        if not isinstance(c, dict):
            continue
        img = c.get("images") or {}
        rows.append({
            **c,
            "image_url": img.get("large") or img.get("medium") or img.get("grid") or img.get("small"),
        })
    return normalize_characters(rows)


# ---------------------------------------------------------------- Connector

class BangumiConnector:
    """Bangumi 数据源实现。"""

    name = "bangumi"
    manifest: ConnectorManifest = None

    def __init__(self):
        self.manifest = load_manifest(_MANIFEST_PATH)
        rpm = (self.manifest.rate_limit or {}).get("requests_per_minute", 20)
        self._bucket = TokenBucket(rpm)
        self._cache = RequestCache(namespace=self.name)
        self.proxy_url = None  # 出站代理（可选，registry.apply_settings 注入）

    # ---- HTTP ----
    def _request(self, method: str, path: str, **kwargs) -> Any:
        self._bucket.acquire()
        url = self.manifest.base_url.rstrip("/") + path
        try:
            if method == "POST":
                resp = http_post(url, timeout=15.0, proxy=self.proxy_url, **kwargs)
            else:
                resp = http_get(url, timeout=15.0, proxy=self.proxy_url, **kwargs)
        except httpx.HTTPError as e:
            raise ConnectorError(f"Bangumi API 请求失败：{e}") from e
        if resp.status_code == 429:
            raise RateLimitError("Bangumi API 限流，请稍后再试。")
        if resp.status_code >= 400:
            raise ConnectorError(f"Bangumi API 返回 {resp.status_code}")
        return resp.json()

    # ---- Protocol 实现 ----
    def search(self, query: str, **filters) -> List[SearchResult]:
        if not query or not query.strip():
            return []
        subject_type = filters.get("type")
        cache_key = f"search:{query.strip()}:{subject_type or ''}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return [_subject_to_search_result(s) for s in cached]

        body = {"keyword": query.strip(), "limit": 20}
        if subject_type is not None:
            body["filter"] = {"type": [subject_type]}
        # 注意：Bangumi v0 搜索端点是 POST（GET 会 404），经本地代理打通后实测确认
        data = self._request("POST", "/v0/search/subjects", json_body=body)
        subjects = data.get("data") or []
        self._cache.set(cache_key, subjects)
        return [_subject_to_search_result(s) for s in subjects]

    def get_detail(self, external_id: str) -> ItemDetail:
        cache_key = f"detail:{external_id}"
        chars_key = f"detail_chars:{external_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            detail = _subject_to_detail(cached)
            detail.metadata["characters"] = self._cache.get(chars_key) or []
            return detail

        subject = self._request("GET", f"/v0/subjects/{external_id}")
        self._cache.set(cache_key, subject)

        # 角色列表是独立端点（subject 详情不含角色）；失败不阻塞详情
        chars: List[dict] = []
        try:
            chars_data = self._request("GET", f"/v0/subjects/{external_id}/characters")
            chars = _characters_to_normalized(chars_data)
        except ConnectorError:
            chars = []
        self._cache.set(chars_key, chars)

        detail = _subject_to_detail(subject)
        detail.metadata["characters"] = chars
        return detail

    def get_collections(self, access_token: str, offset: int = 0, limit: int = 30,
                        subject_type: int = 2) -> Dict[str, Any]:
        """分页拉取当前用户收藏（批量导入用，OAuth 鉴权）。

        复用 `_request`（令牌桶限流 + 代理），不另起一套调用逻辑。
        返回 {"data": [...], "total": N, "limit", "offset"}，条目含
        subject_id / rate / type（1想看 2看过 3在看 4搁置 5抛弃）/ subject 摘要。
        """
        username = self._resolve_username(access_token)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "Tsumugi/0.1 (personal knowledge base)",
        }
        params = {"offset": offset, "limit": limit, "subject_type": subject_type}
        return self._request("GET", f"/v0/users/{username}/collections",
                             params=params, headers=headers)

    def _resolve_username(self, access_token: str) -> str:
        """收藏接口需要真实用户名（`/v0/users/-` 无效）。先从 token 文件缓存取，
        没有则调 `/v0/me` 解析并缓存。"""
        from app import bangumi_oauth
        cached = bangumi_oauth.get_username_from_tokens()
        if cached:
            return cached
        resp = http_get(
            "https://api.bgm.tv/v0/me", timeout=20.0, proxy=self.proxy_url,
            headers={"Authorization": f"Bearer {access_token}",
                     "User-Agent": "Tsumugi/0.1 (personal knowledge base)"},
        )
        if resp.status_code >= 400:
            raise ConnectorError(f"Bangumi 获取用户信息返回 {resp.status_code}")
        username = (resp.json() or {}).get("username")
        if not username:
            raise ConnectorError("Bangumi /v0/me 未返回 username")
        bangumi_oauth.save_username(username)
        return username

    def normalize(self, raw: dict) -> dict:
        """把外部 API 原始返回转换成本地 Item 的字段字典（用于收藏入库）。"""
        result = _subject_to_search_result(raw)
        return {
            "title": result.title,
            "type": "external_ref",
            "content": result.description or "",
            "image_url": result.image_url,
            "source": self.name,
            "external_id": result.external_id,
            "raw_metadata": raw,
            "tags": result.tags,
        }


def build_connector() -> BangumiConnector:
    return BangumiConnector()
