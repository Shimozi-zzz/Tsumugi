"""AniList Connector - search/get_detail（GraphQL）实现（Phase 11-A）

- 使用 AniList 公开 GraphQL API（https://graphql.anilist.co），无需 API Key；
- GraphQL response 一律转换为 Tsumugi 统一模型（SearchResult / ItemDetail），
  不把 AniList 类型直接泄漏进数据库或 React；
- 复用 base 基础设施：http_post / RequestCache / TokenBucket / 代理 / timeout；
- 所有解析防御 null / 缺字段 / malformed / HTTP / GraphQL errors，
  任何异常都包装为 ConnectorError，不影响其它 Provider。
"""
import html
import re
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
    http_post,
    load_manifest,
    normalize_characters,
)

_MANIFEST_PATH = __file__ and (__import__("pathlib").Path(__file__).parent / "manifest.json")

# 媒体类型 → 本地 work_type（与 WORK_TYPES 对齐）
_MEDIA_TYPE_MAP = {"ANIME": "anime", "MANGA": "manga"}


def _pick_title(title_obj: Any):
    """从 AniList title{romaji,english,native} 选主标题与副标题。"""
    if not isinstance(title_obj, dict):
        return ("", "")
    romaji = (title_obj.get("romaji") or "").strip()
    english = (title_obj.get("english") or "").strip()
    native = (title_obj.get("native") or "").strip()
    for primary in (romaji, english, native):
        if primary:
            subtitle = next((s for s in (english, native, romaji) if s and s != primary), "")
            return (primary, subtitle)
    return ("", "")


def _strip_html(text: Any) -> str:
    if not isinstance(text, str) or not text.strip():
        return ""
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _format_date(d: Any) -> str:
    """AniList startDate{year,month,day} → "YYYY-MM-DD" / "YYYY-MM" / "YYYY" / ""。"""
    if not isinstance(d, dict):
        return ""
    year = d.get("year")
    month = d.get("month")
    day = d.get("day")
    if year is None:
        return ""
    if month is None:
        return str(year)
    if day is None:
        return f"{year:04d}-{month:02d}"
    return f"{year:04d}-{month:02d}-{day:02d}"


def _media_type(media: dict) -> str:
    t = (media.get("type") or "").upper()
    return _MEDIA_TYPE_MAP.get(t, t.lower())


def _media_to_search_result(media: Dict[str, Any]) -> SearchResult:
    title, subtitle = _pick_title(media.get("title"))
    tags = [t.get("name") for t in (media.get("tags") or []) if isinstance(t, dict) and t.get("name")]
    cover = (media.get("coverImage") or {})
    score = media.get("averageScore")
    mtype = _media_type(media)
    return SearchResult(
        source="anilist",
        title=title or "",
        external_id=str(media.get("id", "")),
        subtitle=subtitle or None,
        description=_strip_html(media.get("description")),
        image_url=cover.get("extraLarge") or cover.get("large"),
        rating=(float(score) / 10.0) if isinstance(score, (int, float)) else None,
        tags=tags[:8],
        raw=media,
        year=(media.get("startDate") or {}).get("year"),
        type=mtype,
        external_url=f"https://anilist.co/{mtype if mtype == 'manga' else 'anime'}/{media.get('id', '')}",
    )


def _media_to_detail(media: Dict[str, Any]) -> ItemDetail:
    title, subtitle = _pick_title(media.get("title"))
    tags = [t.get("name") for t in (media.get("tags") or []) if isinstance(t, dict) and t.get("name")]
    cover = (media.get("coverImage") or {})
    score = media.get("averageScore")
    mtype = _media_type(media)

    # 角色：edges → node + voiceActors(JAPANESE)，统一 normalize_characters 结构
    char_rows: List[dict] = []
    for edge in (media.get("characters") or {}).get("edges") or []:
        node = edge.get("node") or {}
        if not isinstance(node, dict):
            continue
        cname = (node.get("name") or {})
        full = cname.get("full") or cname.get("native") or ""
        if not full:
            continue
        char_rows.append({
            "id": node.get("id"),
            "name": full,
            "image_url": (node.get("image") or {}).get("large"),
            "relation": edge.get("role"),
            "summary": _strip_html(node.get("description")),
            "actors": [
                {"name": (va.get("name") or {}).get("full") or (va.get("name") or {}).get("native")}
                for va in (edge.get("voiceActors") or []) if isinstance(va, dict)
            ],
        })
    characters = normalize_characters(char_rows, actor_name_key="name")

    # Staff：edges → {name, role, source, external_id}
    staff: List[dict] = []
    for edge in (media.get("staff") or {}).get("edges") or []:
        node = edge.get("node") or {}
        if not isinstance(node, dict):
            continue
        sname = (node.get("name") or {})
        full = sname.get("full") or sname.get("native") or ""
        if not full:
            continue
        staff.append({
            "name": full,
            "role": edge.get("role"),
            "source": "anilist",
            "external_id": str(node.get("id", "")),
        })

    # Relations：edges → {relation, title, external_id, source}
    relations: List[dict] = []
    for edge in (media.get("relations") or {}).get("edges") or []:
        node = edge.get("node") or {}
        if not isinstance(node, dict):
            continue
        rtitle, _ = _pick_title(node.get("title"))
        if not rtitle:
            continue
        relations.append({
            "relation": edge.get("relationType"),
            "title": rtitle,
            "external_id": str(node.get("id", "")),
            "source": "anilist",
        })

    return ItemDetail(
        source="anilist",
        title=title or "",
        external_id=str(media.get("id", "")),
        description=_strip_html(media.get("description")),
        image_url=cover.get("extraLarge") or cover.get("large"),
        genres=[g for g in (media.get("genres") or []) if isinstance(g, str)][:12],
        background=media.get("bannerImage") or None,
        status=media.get("status") or None,
        episodes=media.get("episodes") or media.get("chapters") or None,
        staff=staff,
        relations=relations,
        metadata={
            "original_name": subtitle or title,
            "date": _format_date(media.get("startDate")),
            "rating": (float(score) / 10.0) if isinstance(score, (int, float)) else None,
            "tags": tags,
            "type": mtype,
            "genres": [g for g in (media.get("genres") or []) if isinstance(g, str)][:12],
            "background": media.get("bannerImage") or None,
            "status": media.get("status") or None,
            "episodes": media.get("episodes") or media.get("chapters") or None,
            "duration": media.get("duration"),
            "studios": [s.get("name") for s in (media.get("studios") or {}).get("nodes") or []
                        if isinstance(s, dict) and s.get("name")][:8],
            "staff": staff,
            "relations": relations,
            "characters": characters,
        },
    )


_SEARCH_QUERY = """
query ($search: String, $type: MediaType) {
  Page(page: 1, perPage: 20) {
    media(search: $search, type: $type, sort: [SEARCH_MATCH]) {
      id type format title { romaji english native }
      description coverImage { extraLarge large }
      bannerImage averageScore genres tags { name }
      startDate { year } status episodes chapters
    }
  }
}
"""

_DETAIL_QUERY = """
query ($id: Int) {
  Media(id: $id) {
    id type format title { romaji english native }
    description     coverImage { extraLarge large } bannerImage averageScore
    genres tags { name } status episodes chapters volumes duration
    startDate { year month day } endDate { year month day }
    studios { nodes { id name } }
    staff { edges { role node { id name { full native } } } }
    characters { edges { role node { id name { full native } image { large } description }
                         voiceActors(language: JAPANESE) { id name { full native } } } }
    relations { edges { relationType node { id type title { romaji english native } coverImage { large } } } }
  }
}
"""


class AniListConnector:
    """AniList 数据源实现（GraphQL）。"""

    name = "anilist"
    manifest: ConnectorManifest = None

    def __init__(self):
        self.manifest = load_manifest(_MANIFEST_PATH)
        rpm = (self.manifest.rate_limit or {}).get("requests_per_minute", 40)
        self._bucket = TokenBucket(rpm)
        self._cache = RequestCache(namespace=self.name)
        self.proxy_url = None  # 出站代理（可选，registry.apply_settings 注入）

    # ---- GraphQL 请求 ----
    def _graphql(self, query: str, variables: dict) -> Any:
        self._bucket.acquire()
        url = self.manifest.base_url.rstrip("/")
        try:
            resp = http_post(
                url, timeout=15.0, proxy=self.proxy_url,
                headers={"Content-Type": "application/json",
                         "Accept": "application/json"},
                json_body={"query": query, "variables": variables},
            )
        except httpx.HTTPError as e:
            raise ConnectorError(f"AniList API 请求失败：{e}") from e
        if resp.status_code == 429:
            raise RateLimitError("AniList API 限流，请稍后再试。")
        if resp.status_code >= 400:
            raise ConnectorError(f"AniList API 返回 {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as e:
            raise ConnectorError("AniList API 返回了无法解析的响应") from e
        if not isinstance(data, dict):
            raise ConnectorError("AniList API 响应结构异常")
        if data.get("errors"):
            first = (data["errors"][0] or {}) if isinstance(data["errors"], list) else {}
            msg = (first.get("message") if isinstance(first, dict) else None) or "GraphQL 错误"
            raise ConnectorError(f"AniList API 错误：{msg}")
        return data

    # ---- Protocol 实现 ----
    def search(self, query: str, **filters) -> List[SearchResult]:
        if not query or not query.strip():
            return []
        q = query.strip()
        cache_key = f"search:{q}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return [_media_to_search_result(m) for m in cached]

        variables: Dict[str, Any] = {"search": q}
        ft = filters.get("type")
        if ft:
            variables["type"] = "ANIME" if str(ft).lower() in ("anime", "tv", "ova") else "MANGA"
        data = self._graphql(_SEARCH_QUERY, variables)
        media = ((data.get("data") or {}).get("Page") or {}).get("media") or []
        media = [m for m in media if isinstance(m, dict)]
        self._cache.set(cache_key, media)
        return [_media_to_search_result(m) for m in media]

    def get_detail(self, external_id: str) -> ItemDetail:
        cache_key = f"detail:{external_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return _media_to_detail(cached)

        data = self._graphql(_DETAIL_QUERY, {"id": int(external_id)})
        media = (data.get("data") or {}).get("Media")
        if not isinstance(media, dict):
            raise ConnectorError(f"AniList 未找到条目 {external_id}")
        self._cache.set(cache_key, media)
        return _media_to_detail(media)


def build_connector() -> AniListConnector:
    return AniListConnector()
