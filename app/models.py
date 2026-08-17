"""ORM模型定义 - Item/Chunk/Tag/Source"""
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Table, JSON, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base

# 多对多关联表：Item <-> Tag
item_tag_association = Table(
    'item_tags',
    Base.metadata,
    Column('item_id', Integer, ForeignKey('items.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True)
)

# 多对多关联表：Character <-> Item（P4 / ADR 0048：角色实体化）
character_works = Table(
    'character_works',
    Base.metadata,
    Column('character_id', Integer, ForeignKey('characters.id'), primary_key=True),
    Column('item_id', Integer, ForeignKey('items.id'), primary_key=True)
)


class Item(Base):
    """资料条目 - 统一模型，支持多种数据源"""
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)  # "note" | "image" | "external_ref"
    content = Column(Text, nullable=True)  # markdown文本（note类型，含外部摘要转存）
    file_path = Column(String(500), nullable=True)  # 图片路径（image类型）
    # 去重指纹：sha256(文本内容) / sha256(图片文件内容)；NULL 表示历史数据未计算
    content_hash = Column(String(64), nullable=True, index=True)
    # 外部数据源字段（Phase 3，Connector 收藏入库用）
    image_url = Column(String(500), nullable=True)  # 外部封面图链接
    source = Column(String(50), default="local")  # "local" | "bangumi" | ...
    external_id = Column(String(255), nullable=True)  # 数据源原始 ID（去重/二次拉取）
    raw_metadata = Column(JSON, nullable=True)  # 外部 API 原始返回
    synced_at = Column(DateTime(timezone=True), nullable=True)  # 外部数据同步时间
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    # 世界轴列（P1 Work 模型，ADR 0045）：作品类型 / 原名 / 发行日期。
    # type 表示内容形态（note/image/external_ref），work_type 表示作品类型，二者正交。
    # 从 raw_metadata 幂等回填（只填 NULL，不覆盖用户值）；creator/series 等推迟 P4 实体表。
    work_type = Column(String(20), nullable=True, index=True)  # anime/manga/game/galgame/novel/other
    alternative_title = Column(String(255), nullable=True)  # 原名/别名（多来源匹配用）
    release_date = Column(String(20), nullable=True)  # 发行日期（字符串，按需取年份）
    # Phase 11-B：统一作品实体 MediaEntry 关联（可空；旧数据/旧 Item 不受影响）
    media_id = Column(Integer, ForeignKey("media_entries.id"), nullable=True, index=True)

    # 关系
    chunks = relationship("Chunk", back_populates="item", cascade="all, delete-orphan")
    tags = relationship("Tag", secondary=item_tag_association, back_populates="items")
    reviews = relationship("Review", back_populates="item", cascade="all, delete-orphan")
    memories = relationship("Memory", back_populates="item", cascade="all, delete-orphan")
    collection = relationship("Collection", back_populates="item", uselist=False,
                              cascade="all, delete-orphan")
    characters = relationship("Character", secondary=character_works, back_populates="works")
    media_entry = relationship("MediaEntry", back_populates="items")


class Chunk(Base):
    """文本切分块 - note / external_ref / review 内容均产生"""
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    # 可空：NULL=条目自身内容；非空=该 review 的内容（RAG 检索区分来源）
    review_id = Column(Integer, ForeignKey("reviews.id"), nullable=True, index=True)
    # P7（ADR 0051）：直接 Memory（text/milestone）内容参与检索（source_type=memory）
    memory_id = Column(Integer, ForeignKey("memories.id"), nullable=True, index=True)
    content = Column(Text, nullable=False)  # 切分后的文本
    chunk_index = Column(Integer, nullable=False)  # 在原文中的顺序
    embedding_ref = Column(String(255), nullable=True)  # Chroma中的向量ID
    # 来源类型标记（ADR 0025）：note=用户笔记 / review=用户书评 /
    # external_reference=外部下载的百科资料（简介+角色小传，参与 RAG 检索但加权更低）
    source_type = Column(String(20), nullable=True)
    # external_reference 类型的 chunk 记录来源 Connector（bangumi/moegirl/vndb...），
    # 供"这段内容来自XX"展示与按数据源筛选
    connector = Column(String(50), nullable=True)

    # 关系
    item = relationship("Item", back_populates="chunks")
    review = relationship("Review", back_populates="chunks")
    memory = relationship("Memory", back_populates="chunks")


class Tag(Base):
    """标签"""
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)

    # 关系
    items = relationship("Item", secondary=item_tag_association, back_populates="tags")


class Review(Base):
    """作品读后感/书评 - 一个 Item 可有多条（日记式多次记录）"""
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False, index=True)
    title = Column(String(255), nullable=True)  # 评论标题，可空
    content = Column(Text, nullable=False)  # markdown 文本
    rating = Column(Integer, nullable=True)  # 0-10，可空
    status = Column(String(20), nullable=True)  # 想看/在看/看完/搁置/弃坑
    spoiler = Column(Integer, default=0)  # 0/1，SQLite 无 Boolean
    source = Column(String(20), nullable=True)  # 自动导入来源（如 bangumi_collection），去重用
    font_size = Column(Integer, nullable=True)  # 书评编辑器字号（px），null=默认
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关系
    item = relationship("Item", back_populates="reviews")
    chunks = relationship("Chunk", back_populates="review", cascade="all, delete-orphan")


class Memory(Base):
    """记忆条目 - 独立的容器，收纳"图书馆里发生过的、值得被记住的时刻"（v1.1 / ADR 0041）。

    Memory 不是 Review 的视图：Review 只是其中一种素材来源（source_type=review），
    本轮只实现 review 来源；为未来的 text/image/collection/milestone 等类型预留
    source_type 扩展空间（不做白名单硬校验，别把表设计成只能装 Review）。
    Memory 表本身不参与 RAG 检索（语义容器，检索仍走底层 Review 的
    source_type=review 机制，见 ADR 0041）。
    """
    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False, index=True)
    # 素材来源类型：review / collection / text / milestone（P3 起 text+milestone 直接创建）
    source_type = Column(String(20), nullable=False, default="review")
    # 指向具体来源记录的引用（source_type=review 时 = Review.id；collection 时 = item.id；
    # text/milestone 无主记录，为 NULL）。多态引用，不做 FK。
    source_ref = Column(Integer, nullable=True, index=True)
    # 这段记忆发生的时间（时间轴排序用；review 场景 = Review.created_at）
    occurred_at = Column(DateTime(timezone=True), nullable=False, index=True)
    # 简短展示摘要（列表/时间轴展示免实时关联查询完整内容；text 记忆摘要即正文）
    summary = Column(Text, nullable=True)
    # 可选情绪标记（P3 / ADR 0047）：开心/感动/遗憾/怀念/平静/治愈…（固定小集，自由）
    emotion = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    item = relationship("Item", back_populates="memories")
    media = relationship("Media", back_populates="memory", cascade="all, delete-orphan")
    chunks = relationship("Chunk", back_populates="memory", cascade="all, delete-orphan")


class Character(Base):
    """角色实体（P4 / ADR 0048）：跨作品聚合，独立于 raw_metadata。

    从 raw_metadata.detail.metadata.characters 幂等提炼；去重键 = (source, external_id)
    或 (source, name)。actors 存 JSON 数组（声优名）。relation 为合并角色定位（主角优先）。
    """
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(50), nullable=False)
    external_id = Column(String(255), nullable=True)  # 数据源角色 id（跨作品去重键）
    name = Column(String(255), nullable=False, index=True)
    image_url = Column(String(500), nullable=True)
    relation = Column(String(50), nullable=True)  # 主角/主要角色/配角/登场（合并，主角优先）
    summary = Column(Text, nullable=True)
    actors = Column(Text, nullable=True)  # JSON 数组（声优名）
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    works = relationship("Item", secondary=character_works, back_populates="characters")


class Media(Base):
    """附件资源（P3 / ADR 0047）：Memory 的截图/插图/图片记录。"""
    __tablename__ = "media"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False, index=True)
    memory_id = Column(Integer, ForeignKey("memories.id"), nullable=True, index=True)
    file_path = Column(String(500), nullable=False)  # "./data/uploads/xxx.png"
    media_type = Column(String(20), nullable=True)  # image / future: video/audio
    size = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    memory = relationship("Memory", back_populates="media")


class Collection(Base):
    """收藏关系（P2 / ADR 0046）：用户×作品的个人状态，与 Review 分离。

    1:1 关联 items（外部作品）：status=追番状态、added_at=收藏时间、favorite=是否喜欢。
    收藏状态不再是 Review 的职责（历史从"从 Bangumi 导入"Review 迁移到本表）；
    收藏时刻自动生成最轻的 Collection Memory（source_type=collection）。
    """
    __tablename__ = "collections"

    item_id = Column(Integer, ForeignKey("items.id"), primary_key=True)
    status = Column(String(20), nullable=True)  # 想看/在看/看完/搁置/弃坑
    favorite = Column(Integer, default=0)  # 0/1
    added_at = Column(DateTime(timezone=True), nullable=True)  # 收藏时间
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    item = relationship("Item", back_populates="collection")


class Source(Base):
    """已注册的数据源/插件清单（Phase 3）"""
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)  # "local" | "bangumi" ...
    type = Column(String(50), default="local")  # "local" | "connector"
    enabled = Column(Integer, default=1)  # SQLite 无 Boolean，用 0/1
    config_ref = Column(String(500), nullable=True)  # 指向加密密钥引用，不落库明文
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class LLMProviderConfig(Base):
    """LLM Provider 配置（LLM Provider 可插拔化）

    复用 Phase 4 Connector 的持久化模式：config_ref 存 JSON（含环境变量
    占位符如 {DEEPSEEK_API_KEY}，密钥不落明文）；同一时间仅一个 enabled=1。
    """
    __tablename__ = "llm_providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)  # "deepseek" | "ollama" | ...
    provider_type = Column(String(30), nullable=False)  # "openai_compatible" | "ollama"
    base_url = Column(String(500), nullable=False)
    model_id = Column(String(100), nullable=False)
    # api_key 引用：环境变量占位符（如 "{DEEPSEEK_API_KEY}"），不落明文
    api_key_ref = Column(String(200), nullable=True)
    enabled = Column(Integer, default=0)  # 同一时间仅一个启用
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MediaEntry(Base):
    """统一作品实体（Phase 11-B）：同一逻辑作品聚合多 Provider 来源。

    注意命名：现有 Media 表是"记忆附件"（ADR 0047），故本实体命名 MediaEntry。
    Item 仍是持久化入口（Collection/Review/Memory/RAG 依赖 Item.id），
    MediaEntry 是跨来源聚合层；item.media_id 可空，旧 Item 不受影响。
    """
    __tablename__ = "media_entries"

    id = Column(Integer, primary_key=True, index=True)
    canonical_title = Column(String(255), nullable=False, index=True)
    alternative_titles = Column(Text, nullable=True)  # JSON 数组
    description = Column(Text, nullable=True)
    image_url = Column(String(500), nullable=True)
    work_type = Column(String(20), nullable=True)  # anime/manga/game/...
    release_date = Column(String(20), nullable=True)
    year = Column(Integer, nullable=True)
    genres = Column(Text, nullable=True)  # JSON 数组
    status = Column(String(50), nullable=True)
    episodes = Column(Integer, nullable=True)
    background = Column(String(500), nullable=True)
    # Phase 12-C：高价值结构化字段（全 nullable，跨 Provider 稳定）
    duration = Column(String(100), nullable=True)      # 每集时长 / 总时长（Provider 原文）
    season = Column(String(50), nullable=True)         # Spring/Summer/Fall/Winter 或 1-4
    studios = Column(Text, nullable=True)              # JSON 数组（制作公司名）
    themes = Column(Text, nullable=True)               # JSON 数组
    demographics = Column(Text, nullable=True)         # JSON 数组
    external_links = Column(Text, nullable=True)       # JSON 数组 [{label,url,source}]
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    items = relationship("Item", back_populates="media_entry")
    sources = relationship("MediaSource", back_populates="media_entry", cascade="all, delete-orphan")
    staff = relationship("Staff", back_populates="media_entry", cascade="all, delete-orphan")
    relations = relationship("MediaRelation", back_populates="media_entry",
                             cascade="all, delete-orphan", foreign_keys="MediaRelation.media_id")


class MediaSource(Base):
    """一个作品在某 Provider 的来源身份（source + external_id 唯一）。

    支持未来增加 Provider 而不改 MediaEntry 主表：新增 Provider 只新增一行
    MediaSource。raw_metadata 保留该来源的原始数据（不覆盖、可追溯）。
    """
    __tablename__ = "media_sources"

    id = Column(Integer, primary_key=True, index=True)
    media_id = Column(Integer, ForeignKey("media_entries.id"), nullable=False, index=True)
    source = Column(String(50), nullable=False)
    external_id = Column(String(255), nullable=False)
    external_url = Column(String(500), nullable=True)
    source_title = Column(String(255), nullable=True)
    image_url = Column(String(500), nullable=True)
    raw_metadata = Column(JSON, nullable=True)  # 该来源原始 metadata（不覆盖）
    last_synced_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_media_source"),)

    media_entry = relationship("MediaEntry", back_populates="sources")


class Staff(Base):
    """轻量 Staff 实体（Phase 12-B）：从 raw_metadata 提炼的结构化索引。

    - 允许同一 Staff 出现在多个 MediaEntry（不做跨 Provider 强行 Person 合并）；
    - 去重键 (source, external_id, media_id)；external_id 缺失时按 name+media_id 记一条；
    - 原 raw_metadata 中的 staff 保留，本表只是可查询索引。
    """
    __tablename__ = "staff"

    id = Column(Integer, primary_key=True, index=True)
    media_id = Column(Integer, ForeignKey("media_entries.id"), nullable=False, index=True)
    source = Column(String(50), nullable=False)
    external_id = Column(String(255), nullable=True)
    name = Column(String(255), nullable=False)
    role = Column(String(200), nullable=True)
    credit_order = Column(Integer, nullable=True)
    raw_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (UniqueConstraint("source", "external_id", "media_id", name="uq_staff"),)

    media_entry = relationship("MediaEntry", back_populates="staff")


class MediaRelation(Base):
    """作品关系索引（Phase 12-B）：从 raw_metadata.relations 提炼，可查询可跳转。

    - target_media_id 可空：目标作品尚未收藏时保留 title/external_id/source；
    - 未知 relation_type 保留原始字符串，不做强行归类；
    - 禁止为建立关系自动请求目标作品 API。
    """
    __tablename__ = "media_relations"

    id = Column(Integer, primary_key=True, index=True)
    media_id = Column(Integer, ForeignKey("media_entries.id"), nullable=False, index=True)
    source = Column(String(50), nullable=False)
    relation_type = Column(String(100), nullable=True)
    target_title = Column(String(255), nullable=True)
    target_external_id = Column(String(255), nullable=True)
    target_source = Column(String(50), nullable=True)
    target_media_id = Column(Integer, ForeignKey("media_entries.id"), nullable=True, index=True)
    raw_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (UniqueConstraint(
        "media_id", "source", "target_external_id", "relation_type", name="uq_media_relation"),)

    media_entry = relationship("MediaEntry", back_populates="relations",
                               foreign_keys=[media_id])