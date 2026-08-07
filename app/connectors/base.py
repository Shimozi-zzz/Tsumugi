"""Connector 统一抽象：Protocol + 数据结构（Phase 3）

设计目标：新增数据源 = 实现一个 Connector + 一份 manifest + 注册，
不改动核心检索编排代码。详见 docs/decisions/0007-connector-architecture.md。
"""
import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

import httpx

from app.config import settings
from app.connectors.ssrf import SSRFError, check_ssrf_target


class ConnectorError(Exception):
    """Connector 调用外部 API 失败。message 可直接展示给用户。"""


class RateLimitError(ConnectorError):
    """触发了数据源限流。"""


# ---------------------------------------------------------------- 数据结构

@dataclass
class ConnectorManifest:
    """每个 Connector 的自描述元数据。"""
    name: str
    display_name: str
    version: str
    auth_type: str = "none"  # "api_key" | "oauth" | "none"
    base_url: str = ""
    rate_limit: Optional[Dict[str, Any]] = None  # {"requests_per_minute": 60}
    capabilities: List[str] = field(default_factory=list)  # ["search", "get_detail"]

    @classmethod
    def from_dict(cls, data: dict) -> "ConnectorManifest":
        return cls(
            name=data["name"],
            display_name=data.get("display_name", data["name"]),
            version=data.get("version", "0.0.0"),
            auth_type=data.get("auth_type", "none"),
            base_url=data.get("base_url", ""),
            rate_limit=data.get("rate_limit"),
            capabilities=data.get("capabilities", []),
        )


@dataclass
class SearchResult:
    """外部搜索的轻量结果（未落库，用于联合搜索结果列表展示）。"""
    source: str
    title: str
    external_id: str
    subtitle: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    rating: Optional[float] = None
    tags: List[str] = field(default_factory=list)
    raw: Optional[dict] = None


@dataclass
class ItemDetail:
    """完整详情（角色、关联条目等），点开某条结果时调用。"""
    source: str
    title: str
    external_id: str
    description: str = ""
    image_url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------- Protocol

@runtime_checkable
class Connector(Protocol):
    """统一 Connector 接口。"""

    name: str
    manifest: ConnectorManifest
    proxy_url: Optional[str] = None  # 出站代理（可选，None=直连）；registry.apply_settings 注入

    def search(self, query: str, **filters) -> List[SearchResult]:
        """调用外部 API 搜索，返回未落库的轻量结果。"""

    def get_detail(self, external_id: str) -> ItemDetail:
        """拉取完整详情。"""


# ---------------------------------------------------------------- 基础 HTTP

def _build_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=8.0),
        headers={"User-Agent": "Tsumugi/0.1 (personal knowledge base)"},
    )


def load_manifest(manifest_path: Path) -> ConnectorManifest:
    """从 manifest.json 加载 Connector 元数据。"""
    with open(manifest_path, "r", encoding="utf-8") as f:
        return ConnectorManifest.from_dict(json.load(f))


# ---------------------------------------------------------------- 共享 HTTP 助手（代理支持）

class TokenBucket:
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


class RequestCache:
    """SQLite 简单缓存表：同一 query 短时间内不重复打外部 API。

    namespace：所有 Connector 共用同一张表，若 key 不命名空间隔离会互相污染
    （第三个数据源 VNDB 接入时暴露：bangumi/moegirl/vndb 都用 "search:{q}" 前缀）。
    """

    def __init__(self, db_path: str = None, namespace: str = None):
        self.db_path = db_path or (str(settings.chroma_persist_directory) + "/.connector_cache.db")
        self.namespace = namespace or ""
        self._init()

    def _key(self, key: str) -> str:
        return f"{self.namespace}:{key}" if self.namespace else key

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
                "SELECT payload, fetched_at FROM connector_cache WHERE key = ?", (self._key(key),)
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
                (self._key(key), json.dumps(payload, ensure_ascii=False), time.time()),
            )


def validate_proxy_url(proxy_url: Optional[str], allow_loopback: bool = True) -> None:
    """校验出站代理地址（SSRF 校验），违规抛 ConnectorError。

    代理场景**默认放行回环**（127.0.0.1/localhost/::1）：本地代理软件
    （Clash/V2Ray 等，国内最常见的代理使用方式）默认监听在 127.0.0.1，
    这正是代理配置功能最主要的目标场景——代理地址是用户在设置页主动配置
    的本地/受信地址，风险模型与 Ollama 场景一致（坑位 #29 同款模式），
    不同于 Connector 处理不可信输入 URL 的场景。**其余私网段（10.x/
    172.16.x/192.168.x/169.254.x 云元数据等）仍拦截**——只放行回环，不
    整体放宽。空值（=直连）直接通过。
    """
    if not proxy_url or not str(proxy_url).strip():
        return
    try:
        check_ssrf_target(str(proxy_url), resolve=True, allow_loopback=allow_loopback)
    except SSRFError as e:
        raise ConnectorError(f"代理地址不安全：{e}") from e


def http_get(url: str, *, proxy: Optional[str] = None, headers=None,
             params=None, timeout: float = 15.0) -> httpx.Response:
    """统一出站 GET：可选走代理（connector 级配置）。proxy=None 为直连。"""
    kwargs: Dict[str, Any] = {"headers": headers, "timeout": timeout}
    if params is not None:
        kwargs["params"] = params
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.get(url, **kwargs)


def http_post(url: str, *, proxy: Optional[str] = None, headers=None,
              json_body=None, timeout: float = 15.0) -> httpx.Response:
    """统一出站 POST（JSON body）：可选走代理。proxy=None 为直连。"""
    kwargs: Dict[str, Any] = {"headers": headers, "timeout": timeout}
    if json_body is not None:
        kwargs["json"] = json_body
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.post(url, **kwargs)


# 角色（跨数据源统一的 raw_metadata 内嵌结构，见 ADR 0016）
CHARACTER_FIELDS = ("id", "name", "image_url", "relation", "summary", "actors")


def normalize_characters(raw_characters: List[dict], *, image_key: str = "image_url",
                         actor_name_key: str = "name") -> List[dict]:
    """把数据源返回的角色列表规范化为统一结构。

    统一字段（存入 Item.raw_metadata.metadata.characters，角色墙据此聚合）：
    {id, name, image_url, relation, summary, actors:[声优名]}
    只保留有名字的角色；无名字/无图也保留名字（角色墙可显示占位）。
    """
    result = []
    for c in raw_characters or []:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or c.get("title") or ""
        if not name:
            continue
        result.append({
            "id": c.get("id"),
            "name": str(name),
            "image_url": c.get(image_key),
            "relation": c.get("relation"),
            "summary": c.get("summary") or "",
            "actors": [str(a.get(actor_name_key)) for a in (c.get("actors") or [])
                       if isinstance(a, dict) and a.get(actor_name_key)][:5],
        })
    return result


# ---------------------------------------------------------------- 声明式 Connector（Phase 4）

class DeclarativeConnector:
    """声明式数据源：用户通过配置（HTTP 端点 + 字段映射）接入，不执行任意代码。

    设计动机（AGENTS.md 插件安全边界）：支持用户自建数据源时走**声明式配置**
    而非执行任意 Python 代码；确需代码级插件时才考虑沙箱。声明式只做
    HTTP GET + JSON 字段提取，天然隔离任意代码执行风险。

    配置示例（详见 ADR 0008）：
    {
      "name": "my-api",
      "display_name": "我的API",
      "base_url": "https://api.example.com",
      "search_endpoint": "/search?q={query}",
      "result_path": "results",
      "field_map": {"title": "name", "description": "summary", "external_id": "id"},
      "headers": {"Authorization": "Bearer {api_key}"}
    }
    """

    def __init__(self, config: Dict[str, Any]):
        self.name = str(config["name"])
        self.config = config
        self.manifest = ConnectorManifest(
            name=self.name,
            display_name=str(config.get("display_name", self.name)),
            version=str(config.get("version", "0.1.0")),
            auth_type="api_key" if config.get("headers") else "none",
            base_url=str(config.get("base_url", "")),
            capabilities=["search"],
        )
        self._bucket = None  # 复用 base 的限流？此处用简单节流
        # 出站代理（可选，None=直连）；也可由 registry.apply_settings 注入
        self.proxy_url = config.get("proxy_url") or None
        self._validate()

    def _validate(self) -> None:
        """配置合法性校验：必填字段、字段映射完整性、SSRF 目标/代理预检。"""
        if not self.config.get("base_url"):
            raise ValueError(f"声明式 Connector '{self.name}' 缺少 base_url")
        if not self.config.get("search_endpoint"):
            raise ValueError(f"声明式 Connector '{self.name}' 缺少 search_endpoint")
        fm = self.config.get("field_map") or {}
        missing = [k for k in ("title", "external_id") if k not in fm]
        if missing:
            raise ValueError(f"声明式 Connector '{self.name}' 字段映射缺少 {missing}")
        # SSRF 预检：校验协议 + IP 字面量（不解析域名，创建时保持轻量）
        try:
            check_ssrf_target(str(self.config.get("base_url")), resolve=False)
        except SSRFError as e:
            raise ValueError(f"声明式 Connector '{self.name}' 配置不安全：{e}")
        # 代理地址全量校验（含 DNS 解析；代理是用户可控的出网目标）
        if self.proxy_url:
            try:
                validate_proxy_url(self.proxy_url)
            except ConnectorError as e:
                raise ValueError(f"声明式 Connector '{self.name}' 代理配置不安全：{e}")

    def _build_url(self, query: str) -> str:
        base = self.config["base_url"].rstrip("/")
        endpoint = self.config["search_endpoint"]
        url = f"{base}/{endpoint.lstrip('/')}"
        url = url.replace("{query}", _urlencode(query))
        # 处理 {api_key} 等占位符
        headers = self.config.get("headers") or {}
        for placeholder, value in headers.items():
            if placeholder.startswith("{"):
                continue
        # 简单替换 {api_key} 占位
        return url.replace("{api_key}", str(headers.get("api_key", "")))

    def _request_headers(self) -> Dict[str, str]:
        headers = dict(self.config.get("headers") or {})
        result = {}
        for k, v in headers.items():
            if "{" in str(v):
                # 占位符如 {api_key}，从 config 的 keys 里取
                inner = str(v).strip("{}")
                result[k] = str(self.config.get(inner, ""))
            else:
                result[k] = str(v)
        return result

    def search(self, query: str, **filters) -> List[SearchResult]:
        if not query or not query.strip():
            return []
        url = self._build_url(query)
        # SSRF 防护：请求前解析域名校验目标 IP（防内网/回环/云元数据）
        try:
            check_ssrf_target(url, resolve=True)
        except SSRFError as e:
            raise ConnectorError(f"{self.name} API 目标地址不安全：{e}") from e
        try:
            resp = http_get(url, headers=self._request_headers(), timeout=15.0,
                            proxy=self.proxy_url)
        except httpx.HTTPError as e:
            raise ConnectorError(f"{self.name} API 请求失败：{e}") from e
        if resp.status_code == 429:
            raise RateLimitError(f"{self.name} API 限流，请稍后再试。")
        if resp.status_code >= 400:
            raise ConnectorError(f"{self.name} API 返回 {resp.status_code}")
        try:
            payload = resp.json()
        except json.JSONDecodeError as e:
            raise ConnectorError(f"{self.name} API 返回非 JSON 数据") from e

        result_path = self.config.get("result_path")
        items = payload
        if result_path:
            for part in str(result_path).split("."):
                items = items.get(part, []) if isinstance(items, dict) else []
        if not isinstance(items, list):
            items = []

        field_map = self.config.get("field_map") or {}
        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            results.append(
                SearchResult(
                    source=self.name,
                    title=_dig(item, field_map.get("title", "title")),
                    external_id=str(_dig(item, field_map.get("external_id", "id"))),
                    subtitle=_dig(item, field_map.get("subtitle")) if field_map.get("subtitle") else None,
                    description=_dig(item, field_map.get("description")) if field_map.get("description") else None,
                    image_url=_dig(item, field_map.get("image_url")) if field_map.get("image_url") else None,
                    rating=_safe_float(_dig(item, field_map.get("rating"))) if field_map.get("rating") else None,
                    tags=_as_list(_dig(item, field_map.get("tags"))) if field_map.get("tags") else [],
                    raw=item,
                )
            )
        return results

    def get_detail(self, external_id: str) -> ItemDetail:
        # 声明式数据源默认无 detail 端点；返回一个仅含基本信息的 ItemDetail
        return ItemDetail(
            source=self.name,
            title=external_id,
            external_id=external_id,
        )

    def normalize(self, raw: dict) -> dict:
        fm = self.config.get("field_map") or {}
        return {
            "title": str(_dig(raw, fm.get("title", "title"))),
            "type": "external_ref",
            "content": str(_dig(raw, fm.get("description")) or ""),
            "image_url": _dig(raw, fm.get("image_url")) if fm.get("image_url") else None,
            "source": self.name,
            "external_id": str(_dig(raw, fm.get("external_id", "id"))),
            "raw_metadata": raw,
            "tags": _as_list(_dig(raw, fm.get("tags"))) if fm.get("tags") else [],
        }


def _urlencode(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s, safe="")


def _dig(item: dict, path: Optional[str]):
    """按点号路径取嵌套字段，如 "data.name"。"""
    if not path:
        return None
    cur = item
    for part in str(path).split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _safe_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _as_list(v):
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    return []
