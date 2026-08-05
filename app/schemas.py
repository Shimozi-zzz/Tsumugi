"""Pydantic schemas - API 请求/响应的数据验证"""
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------- Tag

class TagBase(BaseModel):
    name: str


class Tag(TagBase):
    id: int

    model_config = {"from_attributes": True}


class TagOut(BaseModel):
    """标签响应（含使用数量）。"""
    id: int
    name: str
    count: int = 0


class TagRename(BaseModel):
    """标签重命名。"""
    name: str


class TagMerge(BaseModel):
    """标签合并：把 source_tag_ids 全部合并进 target_tag_id 并删除前者。"""
    target_tag_id: int
    source_tag_ids: List[int]


# ---------------------------------------------------------------- Item

class ItemCreate(BaseModel):
    """JSON 方式创建条目。type: "note" | "image" """
    title: str
    type: str = "note"
    content: Optional[str] = None
    file_path: Optional[str] = None
    tag_names: Optional[List[str]] = None
    force: bool = False  # True 时跳过内容去重，强制再导入


class ItemOut(BaseModel):
    """条目响应（含 tags 与 chunks_count，便于前端展示）。"""
    id: int
    title: str
    type: str
    content: Optional[str] = None
    file_path: Optional[str] = None
    image_url: Optional[str] = None
    source: str = "local"
    external_id: Optional[str] = None
    synced_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    tags: List[str] = []
    chunks_count: int = 0


class IngestResponse(BaseModel):
    item_id: int
    title: str
    type: str
    chunks_count: int
    tags: List[str] = []
    duplicated: bool = False  # 内容已存在，本次跳过入库


# ---------------------------------------------------------------- 检索

class QueryRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5
    tag_filter: Optional[List[str]] = None
    max_chunks_per_item: Optional[int] = None
    tag_match: str = "any"  # "any"=任意标签命中, "all"=全部命中（交集）


# ---------------------------------------------------------------- 列表筛选

class ItemFilter(BaseModel):
    """结构化筛选（Phase 2）：标签组合过滤 + 类型/来源过滤。"""
    tag_filter: Optional[List[str]] = None
    tag_match: str = "any"  # any / all
    type: Optional[str] = None  # note / image
    source: Optional[str] = None


class ItemListResponse(BaseModel):
    total: int
    items: List["ItemOut"]


class RetrievedChunk(BaseModel):
    content: str
    item_title: str
    item_id: int
    score: float
    tags: List[str] = []


class SearchResponse(BaseModel):
    results: List[RetrievedChunk]


# ---------------------------------------------------------------- Connector（Phase 3）

class ExternalResult(BaseModel):
    """Connector 联合检索的轻量结果（未落库）。"""
    source: str
    title: str
    subtitle: Optional[str] = None  # 如日文原名/英文名
    description: Optional[str] = None
    image_url: Optional[str] = None
    external_id: str
    rating: Optional[float] = None
    tags: List[str] = []
    raw: Optional[dict] = None


class FederatedSearchResponse(BaseModel):
    """联合检索响应：按来源分组。"""
    query: str
    results: List[ExternalResult]
    local_results: List[RetrievedChunk] = []
    errors: Dict[str, str] = {}  # 各数据源失败信息（降级提示用）


class SaveExternalRequest(BaseModel):
    """收藏入库请求：把外部搜索结果存入本地。"""
    source: str
    external_id: str
    title: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    tags: Optional[List[str]] = None


# ---------------------------------------------------------------- 声明式 Connector（Phase 4）

class DeclarativeConnectorConfig(BaseModel):
    """声明式自定义数据源配置。

    - base_url + search_endpoint：搜索请求端点，`{query}` 占位符替换关键词；
    - result_path：响应中结果数组的路径（如 "data.items"，支持点号嵌套）；
    - field_map：外部字段 -> 本地字段映射（title/external_id 必填）；
    - headers：请求头，值可为 "{env_var}" 引用环境变量（密钥不落库明文）。
    """
    name: str
    display_name: Optional[str] = None
    base_url: str
    search_endpoint: str
    result_path: Optional[str] = None
    field_map: Dict[str, str]
    headers: Optional[Dict[str, str]] = None
    version: Optional[str] = "0.1.0"


# ---------------------------------------------------------------- RAG

class RAGResponse(BaseModel):
    answer: str
    retrieved_chunks: List[RetrievedChunk]
