"""Jikan (MyAnimeList 非官方 API) Connector - search/get_detail 实现（Phase 12-B）

- 公开 API，无需 Key；Jikan 非官方，rate limit 3 req/s，需尊重 429；
- 复用 base 基础设施：http_get / RequestCache / TokenBucket / 代理 / timeout；
- 所有解析防御 null / 缺字段 / malformed / HTTP / 429 / timeout；
- search 同时查 anime + manga；get_detail 用 /full 一次拉取
  characters / staff / relations / studios / season / themes / external。
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
    http_get,
    load_manifest,
    normalize_characters,
)

_MANIFEST_PATH = __file__ and (__import__("pathlib").Path(__file__).parent / "manifest.json")


def _strip_html(text: Any) -> str:
    if not isinstance(text, str) or not text.strip():
        return ""
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _year_from_date(d: Any) -> Optional[int]:
    """Jikan aired/published:{from,to} → 起始年份。"""
    if not isinstance(d, dict):
        return None
    f = d.get("from")
    if isinstance(f, str) and f[:4].isdigit():
        return int(f[:4])
    return None


def _date_str(d: Any) -> str:
    if not isinstance(d, dict):
        return ""
    f = d.get("from")
    if isinstance(f, str):
        return f[:10]
    return ""


def _primary_title(item: dict) -> str:
    return item.get("title") or item.get("name") or item.get("title_english") or ""


def _subtitle(item: dict) -> Optional[str]:
    for k in ("title_english", "title_japanese"):
        v = item.get(k)
        if v and v != item.get("title") and v != item.get("name"):
            return v
    return None


def _tags(item: dict) -> List[str]:
    out = []
    for key in ("genres", "themes", "demographics"):
        for g in item.get(key) or []:
            if isinstance(g, dict) and g.get("name") and g["name"] not in out:
                out.append(g["name"])
    return out[:8]


def _external_url(item: dict, mtype: str) -> str:
    url = item.get("url")
    if url:
        return url
    mal_id = item.get("mal_id")
    if mal_id:
        return f"https://myanimelist.net/{mtype}/{mal_id}"
    return ""


def _media_to_search_result(item: dict, mtype: str) -> SearchResult:
    images = (item.get("images") or {}).get("jpg") or {}
    return SearchResult(
        source="jikan",
        title=_primary_title(item),
        external_id=str(item.get("mal_id", "")),
        subtitle=_subtitle(item),
        description=_strip_html(item.get("synopsis")),
        image_url=images.get("large_image_url") or images.get("image_url"),
        rating=float(item["score"]) if isinstance(item.get("score"), (int, float)) else None,
        tags=_tags(item),
        raw=item,
        year=_year_from_date(item.get("aired") or item.get("published")),
        type=mtype,
        external_url=_external_url(item, mtype),
    )


_SEARCH_QUERIES = {
    "anime": "/anime",
    "manga": "/manga",
}


class JikanConnector:
    """Jikan / MyAnimeList 数据源实现。"""

    name = "jikan"
    manifest: ConnectorManifest = None

    def __init__(self):
        self.manifest = load_manifest(_MANIFEST_PATH)
        rpm = (self.manifest.rate_limit or {}).get("requests_per_minute", 30)
        self._bucket = TokenBucket(rpm)
        self._cache = RequestCache(namespace=self.name)
        self.proxy_url = None

    # ---- HTTP ----
    def _request(self, path: str, params: Optional[dict] = None) -> Any:
        self._bucket.acquire()
        url = self.manifest.base_url.rstrip("/") + path
        try:
            resp = http_get(url, timeout=15.0, proxy=self.proxy_url, params=params)
        except httpx.HTTPError as e:
            raise ConnectorError(f"Jikan API 请求失败：{e}") from e
        if resp.status_code == 429:
            raise RateLimitError("Jikan API 限流，请稍后再试。")
        if resp.status_code == 404:
            raise ConnectorError("Jikan 未找到该条目", )
        if resp.status_code >= 400:
            raise ConnectorError(f"Jikan API 返回 {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as e:
            raise ConnectorError("Jikan API 返回了无法解析的响应") from e
        return data if isinstance(data, dict) else {}

    # ---- Protocol 实现 ----
    def search(self, query: str, **filters) -> List[SearchResult]:
        if not query or not query.strip():
            return []
        q = query.strip()
        results: List[SearchResult] = []
        mtype = filters.get("type")  # 可选：anime / manga
        targets = [mtype] if mtype in _SEARCH_QUERIES else list(_SEARCH_QUERIES)
        for t in targets:
            cache_key = f"search:{q}:{t}"
            cached = self._cache.get(cache_key)
            if cached is not None:
                results += [_media_to_search_result(m, t) for m in cached]
                continue
            data = self._request(_SEARCH_QUERIES[t], params={"q": q, "limit": 10, "sfw": True})
            items = [m for m in (data.get("data") or []) if isinstance(m, dict)]
            self._cache.set(cache_key, items)
            results += [_media_to_search_result(m, t) for m in items]
        return results

    def get_detail(self, external_id: str) -> ItemDetail:
        cache_key = f"detail:{external_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return _media_to_detail(cached["media"], cached["type"])

        # anime / manga ID 独立命名空间：先试 anime，404 再试 manga
        for mtype in ("anime", "manga"):
            try:
                data = self._request(f"/{mtype}/{external_id}/full")
            except ConnectorError as e:
                if "未找到" in str(e) or "404" in str(e):
                    continue
                raise
            media = data.get("data")
            if isinstance(media, dict):
                self._cache.set(cache_key, {"media": media, "type": mtype})
                return _media_to_detail(media, mtype)
        raise ConnectorError(f"Jikan 未找到条目 {external_id}")


def _media_to_detail(media: dict, mtype: str) -> ItemDetail:
    images = (media.get("images") or {}).get("jpg") or {}
    title = _primary_title(media)

    # 角色：characters[].character + voice_actors
    char_rows: List[dict] = []
    for c in media.get("characters") or []:
        ch = c.get("character") or {}
        if not isinstance(ch, dict):
            continue
        name = ch.get("name")
        if not name:
            continue
        va = [{"name": (v.get("person") or {}).get("name")}
              for v in (c.get("voice_actors") or []) if isinstance(v, dict) and v.get("person")]
        char_rows.append({
            "id": ch.get("mal_id"),
            "name": name,
            "image_url": ((ch.get("images") or {}).get("jpg") or {}).get("large_image_url"),
            "relation": c.get("role"),
            "summary": "",
            "actors": [x for x in va if x.get("name")],
        })
    characters = normalize_characters(char_rows, actor_name_key="name")

    # Staff：staff[].person + positions（credit_order = 索引）
    staff: List[dict] = []
    for i, s in enumerate(media.get("staff") or []):
        person = s.get("person") or {}
        if not isinstance(person, dict):
            continue
        name = person.get("name")
        if not name:
            continue
        staff.append({
            "name": name,
            "role": ", ".join(str(p) for p in (s.get("positions") or [])[:4]),
            "source": "jikan",
            "external_id": str(person.get("mal_id", "")),
            "credit_order": i,
        })

    # Relations：relations[].entry[]（entry 可能是 anime/manga）
    relations: List[dict] = []
    for rel in media.get("relations") or []:
        rtype = rel.get("relation")
        for entry in rel.get("entry") or []:
            if not isinstance(entry, dict):
                continue
            ename = entry.get("name")
            if not ename:
                continue
            relations.append({
                "relation": rtype,
                "title": ename,
                "external_id": str(entry.get("mal_id", "")),
                "source": "jikan",
            })

    return ItemDetail(
        source="jikan",
        title=title,
        external_id=str(media.get("mal_id", "")),
        description=_strip_html(media.get("synopsis")),
        image_url=images.get("large_image_url") or images.get("image_url"),
        genres=[g.get("name") for g in (media.get("genres") or []) if isinstance(g, dict) and g.get("name")][:12],
        background=None,
        status=media.get("status") or None,
        episodes=media.get("episodes") or media.get("chapters") or None,
        staff=staff,
        relations=relations,
        metadata={
            "original_name": _subtitle(media) or media.get("title_japanese"),
            "date": _date_str(media.get("aired") or media.get("published")),
            "rating": float(media["score"]) if isinstance(media.get("score"), (int, float)) else None,
            "tags": _tags(media),
            "type": mtype,
            "genres": [g.get("name") for g in (media.get("genres") or []) if isinstance(g, dict) and g.get("name")][:12],
            "themes": [g.get("name") for g in (media.get("themes") or []) if isinstance(g, dict) and g.get("name")][:12],
            "demographics": [g.get("name") for g in (media.get("demographics") or []) if isinstance(g, dict) and g.get("name")][:6],
            "status": media.get("status") or None,
            "episodes": media.get("episodes") or media.get("chapters") or None,
            "duration": media.get("duration") or None,
            "season": media.get("season") or None,
            "season_year": media.get("year"),
            "studios": [s.get("name") for s in (media.get("studios") or []) if isinstance(s, dict) and s.get("name")][:6],
            "external_links": [{"name": e.get("name"), "url": e.get("url")}
                               for e in (media.get("external") or []) if isinstance(e, dict)][:8],
            "characters": characters,
            "staff": staff,
            "relations": relations,
        },
    )


def build_connector() -> JikanConnector:
    return JikanConnector()
