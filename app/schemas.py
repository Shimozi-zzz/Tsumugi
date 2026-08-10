"""Pydantic schemas - API 请求/响应的数据验证"""
from datetime import datetime
from typing import Any, Dict, List, Optional

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
    # P1 Work 模型世界轴列（ADR 0045）
    work_type: Optional[str] = None
    alternative_title: Optional[str] = None
    release_date: Optional[str] = None


class WorkUpdate(BaseModel):
    """手动编辑作品档案的世界轴列（P1，详情页外部世界区内联编辑）。"""
    work_type: Optional[str] = None
    alternative_title: Optional[str] = None
    release_date: Optional[str] = None


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
    # 按来源类型过滤检索（ADR 0025）：note / review / external_reference；
    # None=不过滤。只读用户自己的内容可传 ["note","review"]。
    source_types: Optional[List[str]] = None


# ---------------------------------------------------------------- 列表筛选

class ItemFilter(BaseModel):
    """结构化筛选（Phase 2）：标签组合过滤 + 类型/来源过滤。"""
    tag_filter: Optional[List[str]] = None
    tag_match: str = "any"  # any / all
    type: Optional[str] = None  # note / image
    source: Optional[str] = None


# ---------------------------------------------------------------- 批量操作 / 单条标签（交互打磨）

class ItemTagsRequest(BaseModel):
    """给单个条目增/删/设置标签。"""
    tag_names: List[str] = []
    mode: str = "add"  # add | remove | set


class BatchTagsRequest(BaseModel):
    """批量打标签（对选中的多个条目）。"""
    item_ids: List[int]
    tag_names: List[str] = []
    mode: str = "add"  # add | remove | set


class BatchDeleteRequest(BaseModel):
    """批量删除条目（需前端二次确认）。"""
    item_ids: List[int]


# ---------------------------------------------------------------- Bangumi OAuth / 批量导入

class BangumiOAuthConfig(BaseModel):
    """Bangumi 应用凭证（client_id/client_secret，写入 .env 不落库）。"""
    client_id: str
    client_secret: str


class BangumiOAuthStatusOut(BaseModel):
    connected: bool
    config_configured: bool
    user_id: Optional[str] = None
    expires_at: Optional[float] = None
    redirect_uri: Optional[str] = None


class BangumiAuthorizeOut(BaseModel):
    authorize_url: str
    redirect_uri: str


class BangumiImportStartOut(BaseModel):
    job_id: str


class BangumiImportStatusOut(BaseModel):
    job_id: str
    state: str  # pending | running | done | error
    total: int = 0
    current: int = 0
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    failures: List[str] = []
    message: str = ""


class ItemListResponse(BaseModel):
    total: int
    items: List["ItemOut"]


# ---------------------------------------------------------------- 外部详情 / 角色墙（角色图鉴）

class ExternalDetailOut(BaseModel):
    """connector.get_detail 的 live 返回（联合搜索结果点开详情用）。"""
    source: str
    title: str
    external_id: str
    description: str = ""
    image_url: Optional[str] = None
    rating: Optional[float] = None
    tags: List[str] = []
    characters: List[dict] = []  # {id,name,image_url,relation,summary,actors}
    metadata: Dict[str, Any] = {}


class ItemDetailOut(BaseModel):
    """已收藏条目详情（含 raw_metadata 提炼出的 detail，供前端详情弹层）。"""
    id: int
    title: str
    source: str
    external_id: Optional[str] = None
    image_url: Optional[str] = None
    file_path: Optional[str] = None  # 本地缓存封面（/static 同源，安利卡导出用）
    description: Optional[str] = None
    rating: Optional[float] = None  # 外部数据源公众评分（如 Bangumi）
    my_rating: Optional[float] = None  # 该 item 全部 Review 评分的均值（无打分=null）
    tags: List[str] = []
    characters: List[dict] = []
    # 完整资料文本（ADR 0025：简介+角色小传），Overview 展示"完整简介"兜底用
    reference_text: Optional[str] = None
    # 热度/评分分布替代数据（ADR 0026：三源无公开评论文本，见 extract_social_meta）
    social: Dict[str, Any] = {}
    raw_metadata: Optional[dict] = None
    created_at: Optional[datetime] = None
    # P1 Work 模型世界轴列（ADR 0045）
    work_type: Optional[str] = None
    alternative_title: Optional[str] = None
    release_date: Optional[str] = None


class RelatedSourceOut(BaseModel):
    """同一作品跨来源收藏的兄弟条目（ADR 0026 多来源切换，按规范化标题匹配）。"""
    id: int
    title: str
    source: str
    external_id: Optional[str] = None
    image_url: Optional[str] = None
    rating: Optional[float] = None


# ---------------------------------------------------------------- 第三方插件（ADR 0027）

class PluginOut(BaseModel):
    """已加载的代码级插件（本地文件信任模型）。"""
    name: str
    display_name: str
    version: str
    capabilities: List[str] = []
    path: str = ""
    enabled: bool = True


class PluginFailureOut(BaseModel):
    """加载失败的插件记录（优雅跳过，不阻塞应用）。"""
    dir: str
    error: str


class PluginsResponse(BaseModel):
    plugin_dir: str
    plugins: List[PluginOut] = []
    failures: List[PluginFailureOut] = []
    notice_needed: bool = False  # 首次检测到插件且未确认风险提示


class CharacterOut(BaseModel):
    """角色墙条目：跨作品聚合后的角色。"""
    id: Optional[int] = None
    name: str
    image_url: Optional[str] = None
    relation: Optional[str] = None
    summary: str = ""
    actors: List[str] = []
    source: str
    works: List[dict] = []  # [{item_id, title, image_url, source}]


class CharactersResponse(BaseModel):
    characters: List[CharacterOut]


# ---------------------------------------------------------------- Review（读后感）

class ReviewCreate(BaseModel):
    """创建 review。"""
    content: str
    title: Optional[str] = None
    rating: Optional[int] = None  # 0-10
    status: Optional[str] = None  # 想看/在看/看完/搁置/弃坑
    spoiler: bool = False
    font_size: Optional[int] = None  # 编辑器字号（px）


class ReviewUpdate(BaseModel):
    """编辑 review（全字段可选，缺省不变）。"""
    content: Optional[str] = None
    title: Optional[str] = None
    rating: Optional[int] = None
    status: Optional[str] = None
    spoiler: Optional[bool] = None
    font_size: Optional[int] = None


class ReviewOut(BaseModel):
    """review 响应（含关联 item 摘要与大众评分对比）。"""
    id: int
    item_id: int
    item_title: str = ""
    title: Optional[str] = None
    content: str
    rating: Optional[int] = None
    status: Optional[str] = None
    spoiler: bool = False
    font_size: Optional[int] = None
    public_rating: Optional[float] = None  # 外部数据源大众评分（如 Bangumi）
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MemoryOut(BaseModel):
    """记忆条目响应（Phase A / ADR 0041）。

    Memory 是独立容器；source_type 本轮为 review，未来扩展 text/image/
    collection/milestone。summary 为简短摘要，列表/时间轴展示用。
    """
    id: int
    item_id: int
    item_title: str = ""
    source_type: str = "review"
    source_ref: Optional[int] = None
    occurred_at: Optional[datetime] = None
    summary: Optional[str] = None
    created_at: Optional[datetime] = None


class RetrievedChunk(BaseModel):
    content: str
    item_title: str
    item_id: int
    score: float
    tags: List[str] = []
    # 来源类型（ADR 0025）：note=用户笔记 / review=用户书评 /
    # external_reference=外部下载的百科资料。review_id 对应 review 内容。
    source_type: str = "note"
    review_id: Optional[int] = None
    review_title: Optional[str] = None
    # external_reference 的来源 Connector（bangumi/moegirl/vndb...），用于
    # "这段内容来自XX"展示与按数据源区分
    connector: Optional[str] = None


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


class ConnectorProxyRequest(BaseModel):
    """设置 Connector 出站代理。proxy_url 留空/空串 = 清除（直连）。"""
    proxy_url: Optional[str] = None


# ---------------------------------------------------------------- RAG

class RAGResponse(BaseModel):
    answer: str
    retrieved_chunks: List[RetrievedChunk]


# ---------------------------------------------------------------- LLM Provider（可插拔化）

class LLMProviderCreate(BaseModel):
    """保存 provider 配置。api_key 用环境变量占位符（如 {MY_KEY}）。"""
    name: str
    provider_type: str = "openai_compatible"  # "openai_compatible" | "ollama"
    base_url: str
    model_id: str
    api_key_ref: Optional[str] = None
    enabled: bool = False


class LLMProviderOut(BaseModel):
    """provider 响应（不下发明文 key，仅占位符）。"""
    id: int
    name: str
    provider_type: str
    base_url: str
    model_id: str
    api_key_ref: Optional[str] = None
    enabled: bool = False


class LLMProviderList(BaseModel):
    providers: List[LLMProviderOut] = []
    enabled_name: Optional[str] = None


class LLMTestRequest(BaseModel):
    """测试连接：可针对已保存配置或临时配置。"""
    name: Optional[str] = None  # 已保存的 provider 名
    provider_type: Optional[str] = None
    base_url: Optional[str] = None
    model_id: Optional[str] = None
    api_key_ref: Optional[str] = None


class LLMTestResponse(BaseModel):
    ok: bool
    message: str
