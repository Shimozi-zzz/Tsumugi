from datetime import datetime
from typing import Any, Literal
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field

from backend.services.thumbnail_service import build_thumb_api_url


MediaSaveMode = Literal["none", "link_only", "download"]
CollectionType = Literal["series", "custom"]
NoteType = Literal["work", "character", "misc"]


class MediaPathSchema(BaseModel):
    """游戏媒体资产路径与本地启动配置（完整视图/创建用）"""

    model_config = ConfigDict(from_attributes=True)

    cover_path: str = ""
    cover_thumb_path: str = ""
    logo_path: str = ""
    hero_bg_path: str = ""
    custom_spine_path: str = ""
    pv_url_or_path: str = ""
    pv_remote_url: str = ""
    pv_mode: str = "none"
    exe_path: str = ""
    launch_mode: str = "direct"
    launch_args: str = ""
    save_dir: str = ""
    screenshot_dir: str = ""
    bgm_path: str = ""
    bgm_remote_url: str = ""
    bgm_mode: str = "none"


class MediaPathUpdateSchema(BaseModel):
    """游戏媒体与启动配置局部更新模型（仅修改明确传入的字段）"""

    cover_path: str | None = None
    cover_thumb_path: str | None = None
    logo_path: str | None = None
    hero_bg_path: str | None = None
    custom_spine_path: str | None = None
    pv_url_or_path: str | None = None
    pv_remote_url: str | None = None
    pv_mode: MediaSaveMode | None = None
    exe_path: str | None = None
    launch_mode: str | None = None
    launch_args: str | None = None
    save_dir: str | None = None
    screenshot_dir: str | None = None
    bgm_path: str | None = None
    bgm_remote_url: str | None = None
    bgm_mode: MediaSaveMode | None = None


class PlayRecordSchema(BaseModel):
    """累计游玩时长汇总"""

    model_config = ConfigDict(from_attributes=True)

    total_seconds: int = 0
    last_played_at: datetime | None = None


class PlaySessionOut(BaseModel):
    """单次游玩历史明细"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    game_id: int
    started_at: datetime
    duration_seconds: int


class GameCreate(BaseModel):
    """手动或程序创建游戏请求体"""

    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(..., min_length=1, max_length=255, description="游戏标题")
    sub_title: str = ""
    developer: str = ""
    publisher: str = ""
    release_date: str = ""
    synopsis: str = ""
    tags: list[str] = Field(default_factory=list)
    status: str = "todo"
    edition: str = "collector"
    is_nsfw: bool = Field(default=False, validation_alias=AliasChoices("is_nsfw", "in_nsfw"))
    source_platform: str = "PC"
    bangumi_id: str = ""
    series: str = ""
    external_ids: dict[str, Any] = Field(default_factory=dict)
    locked_fields: list[str] = Field(default_factory=list)
    media: MediaPathSchema | None = None


class GameUpdate(BaseModel):
    """游戏局部更新请求体"""

    model_config = ConfigDict(populate_by_name=True)

    title: str | None = Field(None, min_length=1, max_length=255, description="游戏标题")
    sub_title: str | None = None
    developer: str | None = None
    publisher: str | None = None
    release_date: str | None = None
    synopsis: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    edition: str | None = None
    is_nsfw: bool | None = Field(default=None, validation_alias=AliasChoices("is_nsfw", "in_nsfw"))
    source_platform: str | None = None
    bangumi_id: str | None = None
    series: str | None = None
    external_ids: dict[str, Any] | None = None
    locked_fields: list[str] | None = None
    media: MediaPathUpdateSchema | None = None


class CollectionItemSummary(BaseModel):
    """合集内单部作品轻量摘要（严格按 position 排序）"""

    game_id: int
    title: str
    sub_title: str = ""
    cover_thumb_url: str = ""
    cover_path: str = ""
    play_status: str = "todo"
    is_nsfw: bool = False
    rating_overall: float | None = None
    relation_label: str = ""
    position: int = 0
    added_at: datetime | None = None


class GameCollectionMembership(BaseModel):
    """作品详情附带的所属合集及同系列有序成员列表"""

    id: int
    name: str
    description: str = ""
    collection_type: CollectionType | str = "series"
    relation_label: str = ""
    position: int = 0
    total_count: int = 0
    completed_count: int = 0
    items: list[CollectionItemSummary] = Field(default_factory=list)


class GameOut(BaseModel):
    """游戏完整详情响应模型"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    sub_title: str
    pinyin_initials: str
    developer: str
    publisher: str
    release_date: str
    synopsis: str
    tags: list[str]
    external_ids: dict[str, Any]
    locked_fields: list[str]
    bangumi_id: str = ""
    series: str = ""
    rating_overall: float | None = None
    rating_dimensions: dict[str, float] | None = None
    short_review: str = ""
    status: str
    edition: str
    is_nsfw: bool
    source_platform: str
    created_at: datetime
    media: MediaPathSchema | None = None
    play_record: PlayRecordSchema | None = None
    notes_count: int = 0
    collections: list[GameCollectionMembership] = Field(default_factory=list)

    @computed_field
    @property
    def cover_thumb_url(self) -> str:
        if not self.media:
            return ""
        src = (self.media.cover_path or self.media.cover_thumb_path or "").strip()
        return build_thumb_api_url(src, "sm")

    @computed_field
    @property
    def background_thumb_url(self) -> str:
        if not self.media:
            return ""
        src = (self.media.hero_bg_path or "").strip()
        return build_thumb_api_url(src, "md")


class SettingUpdate(BaseModel):
    value: Any


class AggregateRequest(BaseModel):
    """多源推荐聚合请求"""

    keyword: str = Field(..., min_length=1)
    external_ids: dict[str, str] = Field(default_factory=dict)
    preferred_source: str = ""


class ScraperImportRequest(BaseModel):
    """刮削结果确认入库请求（支持用户微调后提交，由后端本地化下载视觉资产）"""

    title: str = Field(..., min_length=1, max_length=255)
    sub_title: str = ""
    developer: str = ""
    publisher: str = ""
    release_date: str = ""
    synopsis: str = ""
    tags: list[str] = Field(default_factory=list)
    status: str = "todo"
    edition: str = "collector"
    is_nsfw: bool = False
    source_platform: str = "PC"
    bangumi_id: str = ""
    external_ids: dict[str, Any] = Field(default_factory=dict)

    # 远程视觉资产链接
    cover_url: str = ""
    logo_url: str = ""
    hero_bg_url: str = ""
    pv_url: str = ""
    pv_mode: MediaSaveMode | None = None
    selected_pv_url: str | None = None
    selected_pv_source: str | None = None
    selected_pv_mime_hint: str | None = None
    selected_pv_fallback_urls: list[str] = Field(default_factory=list)
    op_mode: MediaSaveMode | None = None
    selected_bgm_url: str | None = None
    screenshots: list[str] = Field(default_factory=list)
    download_screenshots: bool = True
    auto_fetch_bgm: bool = False

    # 本地绑定配置
    exe_path: str = ""
    launch_mode: str = "direct"
    launch_args: str = ""
    save_dir: str = ""
    screenshot_dir: str = ""


class BatchScanRequest(BaseModel):
    root_dir: str = Field(..., min_length=1, description="待扫描的游戏总根目录路径")


class BatchScanCandidate(BaseModel):
    folder_name: str
    folder_path: str
    clean_title: str
    suggested_exe: str = ""
    candidate_exes: list[str] = Field(default_factory=list)
    detected_save_dir: str = ""
    detected_screenshot_dir: str = ""
    already_imported: bool = False


class BatchImportItem(BaseModel):
    title: str = Field(..., min_length=1)
    folder_path: str = ""
    exe_path: str = ""
    launch_mode: str = "direct"
    save_dir: str = ""
    screenshot_dir: str = ""
    edition: str = "collector"


class BatchImportRequest(BaseModel):
    items: list[BatchImportItem] = Field(default_factory=list)
    auto_scrape: bool = True


class BackupCreateRequest(BaseModel):
    note: str = ""


class StopRunningRequest(BaseModel):
    terminate_process: bool = False


class BrowsePathRequest(BaseModel):
    path: str = ""
    extensions: list[str] = Field(default_factory=list)


class ValidatePathRequest(BaseModel):
    path: str = ""


class CollectionItemInput(BaseModel):
    game_id: int
    relation_label: str = Field(default="", max_length=32)


class CollectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    collection_type: CollectionType = "series"
    game_ids: list[int] = Field(default_factory=list)
    items: list[CollectionItemInput] | None = None


class CollectionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=64)
    description: str | None = Field(None, max_length=500)
    collection_type: CollectionType | None = None
    sort_order: int | None = None


class CollectionGamesUpdate(BaseModel):
    game_ids: list[int] = Field(default_factory=list)


class CollectionItemsUpdate(BaseModel):
    items: list[CollectionItemInput] = Field(default_factory=list)


class CollectionOut(BaseModel):
    id: int
    name: str
    description: str = ""
    collection_type: CollectionType | str = "series"
    sort_order: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    game_ids: list[int] = Field(default_factory=list)
    items: list[CollectionItemSummary] = Field(default_factory=list)
    total_count: int = 0
    completed_count: int = 0
    playing_count: int = 0
    unplayed_count: int = 0


class GameRatingUpdate(BaseModel):
    """作品多维评分与一句话短评更新请求"""

    rating_overall: float | None = Field(default=None, ge=1.0, le=10.0)
    rating_dimensions: dict[str, float | None] | None = None
    short_review: str | None = Field(default=None, max_length=500)
    clear: bool = False


class GameNoteCreate(BaseModel):
    note_type: NoteType = "work"
    title: str = Field(default="", max_length=120)
    content_md: str = ""
    is_pinned: bool = False


class GameNoteUpdate(BaseModel):
    note_type: NoteType | None = None
    title: str | None = Field(default=None, max_length=120)
    content_md: str | None = None
    is_pinned: bool | None = None


class GameNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    game_id: int
    note_type: NoteType | str
    title: str
    content_md: str
    is_pinned: bool
    created_at: datetime
    updated_at: datetime


class MusicDownloadRequest(BaseModel):
    source_url: str = ""
    preview_url: str = ""
    mode: MediaSaveMode = "download"
    async_mode: bool = False


class AssetApplyRequest(BaseModel):
    """单项视觉资产 / 宣传片定向替换请求"""

    asset_type: Literal["cover", "logo", "hero", "spine", "pv"]
    url: str = Field(..., min_length=4)
    source: str = ""
    mime_hint: str = ""
    fallback_urls: list[str] = Field(default_factory=list)
    mode: MediaSaveMode = "download"
    async_mode: bool = True


class BangumiSyncRequest(BaseModel):
    """单作手动单向推送游玩状态、评分与短评到 Bangumi"""

    bangumi_id: str | None = None
    sync_rating: bool = True
    rate: int | None = Field(default=None, ge=0, le=10)
    sync_comment: bool = True
    comment: str | None = Field(default=None, max_length=200)
    private: bool | None = None


class ScraperEnrichRequest(BaseModel):
    """跨源字段补全请求（从其他源拉取中文简介或高清封面/背景）"""

    title: str = Field(..., min_length=1)
    original_title: str = ""
    aliases: list[str] = Field(default_factory=list)
    release_date: str = ""
    source: str = ""
    source_id: str = ""
    external_ids: dict[str, str] = Field(default_factory=dict)
    target_sources: list[str] | None = None
    mode: Literal["all", "description", "covers"] = "all"


class ScraperSettingsUpdateRequest(BaseModel):
    """本地 DATA_DIR/settings.json 多源刮削配置更新请求"""

    enabled_sources: dict[str, bool] | None = None
    ymgal_client_id: str | None = None
    ymgal_client_secret: str | None = None
    kungal_base_url: str | None = None
    kungal_token: str | None = None
    bangumi_token: str | None = None
    touchgal_api_key: str | None = None
    steamgriddb_api_key: str | None = None
    igdb_client_id: str | None = None
    igdb_client_secret: str | None = None
    clear_fields: list[str] = Field(default_factory=list)


class ScraperTestRequest(BaseModel):
    """数据源连通性测试请求（可选传入未保存的临时凭证进行实时验证）"""

    ymgal_client_id: str | None = None
    ymgal_client_secret: str | None = None
    kungal_base_url: str | None = None
    kungal_token: str | None = None
    bangumi_token: str | None = None
    touchgal_api_key: str | None = None
    steamgriddb_api_key: str | None = None
    igdb_client_id: str | None = None
    igdb_client_secret: str | None = None
