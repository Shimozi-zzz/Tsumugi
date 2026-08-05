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


class Chunk(Base):
    """文本切分块 - 仅note类型产生"""
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    content = Column(Text, nullable=False)  # 切分后的文本
    chunk_index = Column(Integer, nullable=False)  # 在原文中的顺序
    embedding_ref = Column(String(255), nullable=True)  # Chroma中的向量ID

    # 关系
    item = relationship("Item", back_populates="chunks")


class Tag(Base):
    """标签"""
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)

    # 关系
    items = relationship("Item", secondary=item_tag_association, back_populates="tags")


class Source(Base):
    """已注册的数据源/插件清单（Phase 3）"""
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)  # "local" | "bangumi" ...
    type = Column(String(50), default="local")  # "local" | "connector"
    enabled = Column(Integer, default=1)  # SQLite 无 Boolean，用 0/1
    config_ref = Column(String(500), nullable=True)  # 指向加密密钥引用，不落库明文
    created_at = Column(DateTime(timezone=True), server_default=func.now())