"""ORM模型定义 - Item/Chunk/Tag/Source"""
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Table, JSON
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

    # 关系
    chunks = relationship("Chunk", back_populates="item", cascade="all, delete-orphan")
    tags = relationship("Tag", secondary=item_tag_association, back_populates="items")
    reviews = relationship("Review", back_populates="item", cascade="all, delete-orphan")
    memories = relationship("Memory", back_populates="item", cascade="all, delete-orphan")


class Chunk(Base):
    """文本切分块 - note / external_ref / review 内容均产生"""
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    # 可空：NULL=条目自身内容；非空=该 review 的内容（RAG 检索区分来源）
    review_id = Column(Integer, ForeignKey("reviews.id"), nullable=True, index=True)
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
    # 素材来源类型：review（本轮）/ 预留 text / image / collection / milestone
    source_type = Column(String(20), nullable=False, default="review")
    # 指向具体来源记录的引用（source_type=review 时 = Review.id；多态引用，不做 FK）
    source_ref = Column(Integer, nullable=True, index=True)
    # 这段记忆发生的时间（时间轴排序用；review 场景 = Review.created_at）
    occurred_at = Column(DateTime(timezone=True), nullable=False, index=True)
    # 简短展示摘要（列表/时间轴展示免实时关联查询完整 Review 内容）
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    item = relationship("Item", back_populates="memories")


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