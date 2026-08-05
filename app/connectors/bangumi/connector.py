"""Bangumi Connector - search/get_detail/normalize 实现（Phase 3）

API 文档：https://bangumi.github.io/api/
- GET /v0/search/subjects?keyword=...&type=...&limit=20
- GET /v0/subjects/{subject_id}
搜索响应每条 subject 含：id, name, name_cn, summary, images, rating,
tags, date 等。
"""
import json
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.connectors.base import (
    ConnectorError,
    ConnectorManifest,
    ItemDetail,
    RateLimitError,
    SearchResult,
    load_manifest,
)
from app.models import Item

_MANIFEST_PATH = __file__ and (__import__("pathlib").Path(__file__).parent / "manifest.json")

# Bangumi 条目类型：2=动画 3=书籍 4=音乐 6=游戏
TYPE_ANIME = 2
TYPE_GAME = 6


# ---------------------------------------------------------------- 请求缓存/限流

class _TokenBucket:
    """进程内简单令牌桶限流：尊重 manifest 的 requests_per_minute。"""

    def __init__(self, rate_per_minute: int):
        self.rate = max(rate_per_minute, 1)
        self.interval = 60.0 / self.rate
        self._next_time = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next_time - now
            if wait > 0:
                time.sleep(wait)
                self._next_time += self.interval
            else:
                self._next_time = now + self.interval


class _Cache:
    """SQLite 简单缓存表：同一 query 短时间内不重复打外部 API。"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or (str(settings.chroma_persist_directory) + "/.connector_cache.db")
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS connector_cache (
                    key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    fetched_at REAL NOT NULL
                )
                """
            )

    def get(self, key: str, ttl_seconds: int = 600):
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload, fetched_at FROM connector_cache WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        if time.time() - row["fetched_at"] > ttl_seconds:
            return None  # 过期视为 miss
        try:
            return json.loads(row["payload"])
        except json.JSONDecodeError:
            return None

    def set(self, key: str, payload: Any):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO connector_cache (key, payload, fetched_at) VALUES (?, ?, ?)",
                (key, json.dumps(payload, ensure_ascii=False), time.time()),
            )


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
    return ItemDetail(
        source="bangumi",
        title=subject.get("name_cn") or subject.get("name") or "",
        external_id=str(subject.get("id", "")),
        description=subject.get("summary") or "",
        image_url=(subject.get("images") or {}).get("large"),
        metadata={
            "original_name": subject.get("name"),
            "date": subject.get("date"),
            "rating": (subject.get("rating") or {}).get("score"),
            "tags": [t.get("name") for t in (subject.get("tags") or []) if t.get("name")],
            "type": subject.get("type"),
            "volumes": subject.get("volumes"),
            "eps": subject.get("eps"),
        },
    )


# ---------------------------------------------------------------- Connector

class BangumiConnector:
    """Bangumi 数据源实现。"""

    name = "bangumi"
    manifest: ConnectorManifest = None

    def __init__(self):
        self.manifest = load_manifest(_MANIFEST_PATH)
        rpm = (self.manifest.rate_limit or {}).get("requests_per_minute", 20)
        self._bucket = _TokenBucket(rpm)
        self._cache = _Cache()

    # ---- HTTP ----
    def _request(self, method: str, path: str, **kwargs) -> Any:
        self._bucket.acquire()
        url = self.manifest.base_url.rstrip("/") + path
        try:
            resp = httpx.get(url, timeout=15.0, **kwargs)
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

        params = {"keyword": query.strip(), "limit": 20}
        if subject_type is not None:
            params["type"] = subject_type
        data = self._request("GET", "/v0/search/subjects", params=params)
        subjects = data.get("data") or []
        self._cache.set(cache_key, subjects)
        return [_subject_to_search_result(s) for s in subjects]

    def get_detail(self, external_id: str) -> ItemDetail:
        cache_key = f"detail:{external_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return _subject_to_detail(cached)
        data = self._request("GET", f"/v0/subjects/{external_id}")
        self._cache.set(cache_key, data)
        return _subject_to_detail(data)

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
