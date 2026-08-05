"""Connector 统一抽象：Protocol + 数据结构（Phase 3）

设计目标：新增数据源 = 实现一个 Connector + 一份 manifest + 注册，
不改动核心检索编排代码。详见 docs/decisions/0007-connector-architecture.md。
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

import httpx


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
        self._validate()

    def _validate(self) -> None:
        """配置合法性校验：必填字段与字段映射完整性。"""
        if not self.config.get("base_url"):
            raise ValueError(f"声明式 Connector '{self.name}' 缺少 base_url")
        if not self.config.get("search_endpoint"):
            raise ValueError(f"声明式 Connector '{self.name}' 缺少 search_endpoint")
        fm = self.config.get("field_map") or {}
        missing = [k for k in ("title", "external_id") if k not in fm]
        if missing:
            raise ValueError(f"声明式 Connector '{self.name}' 字段映射缺少 {missing}")

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
        try:
            resp = httpx.get(url, headers=self._request_headers(), timeout=15.0)
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
