from datetime import datetime
from typing import Any
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.db.database import Base


class Game(Base):
    """表 1：游戏核心元数据与书架规格表"""
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    sub_title: Mapped[str] = mapped_column(String(255), default="")
    pinyin_initials: Mapped[str] = mapped_column(String(128), default="", index=True)
    developer: Mapped[str] = mapped_column(String(128), default="")
    publisher: Mapped[str] = mapped_column(String(128), default="")
    release_date: Mapped[str] = mapped_column(String(32), default="")
    synopsis: Mapped[str] = mapped_column(Text, default="")

    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    external_ids: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    locked_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    bangumi_id: Mapped[str] = mapped_column(String(64), default="")
    series: Mapped[str] = mapped_column(String(120), default="")

    rating_overall: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    rating_dimensions: Mapped[dict[str, float] | None] = mapped_column(JSON, nullable=True, default=None)
    short_review: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[str] = mapped_column(String(20), default="todo", index=True)
    edition: Mapped[str] = mapped_column(String(20), default="collector")
    is_nsfw: Mapped[bool] = mapped_column(Boolean, default=False)
    source_platform: Mapped[str] = mapped_column(String(32), default="PC")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    media: Mapped["GameMediaPath"] = relationship(
        back_populates="game", uselist=False, cascade="all, delete-orphan"
    )
    play_record: Mapped["PlayRecord"] = relationship(
        back_populates="game", uselist=False, cascade="all, delete-orphan"
    )
    sessions: Mapped[list["PlaySession"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )
    notes: Mapped[list["GameNote"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )
    collection_items: Mapped[list["CollectionItem"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )


class GameMediaPath(Base):
    """表 2：视觉资产相对路径、外部目录绑定与启动方案表"""
    __tablename__ = "game_media_paths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), unique=True)

    cover_path: Mapped[str] = mapped_column(String(512), default="")
    cover_thumb_path: Mapped[str] = mapped_column(String(512), default="")
    logo_path: Mapped[str] = mapped_column(String(512), default="")
    hero_bg_path: Mapped[str] = mapped_column(String(512), default="")
    custom_spine_path: Mapped[str] = mapped_column(String(512), default="")
    pv_url_or_path: Mapped[str] = mapped_column(String(512), default="")
    pv_remote_url: Mapped[str] = mapped_column(String(1024), default="")
    pv_mode: Mapped[str] = mapped_column(String(20), default="none")

    exe_path: Mapped[str] = mapped_column(String(512), default="")
    launch_mode: Mapped[str] = mapped_column(String(20), default="direct")
    launch_args: Mapped[str] = mapped_column(String(255), default="")
    save_dir: Mapped[str] = mapped_column(String(512), default="")
    screenshot_dir: Mapped[str] = mapped_column(String(512), default="")
    bgm_path: Mapped[str] = mapped_column(String(500), default="")
    bgm_remote_url: Mapped[str] = mapped_column(String(1024), default="")
    bgm_mode: Mapped[str] = mapped_column(String(20), default="none")

    game: Mapped["Game"] = relationship(back_populates="media")


class PlayRecord(Base):
    """表 3A：累计游玩时长汇总表"""
    __tablename__ = "play_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), unique=True)
    total_seconds: Mapped[int] = mapped_column(Integer, default=0)
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    game: Mapped["Game"] = relationship(back_populates="play_record")


class PlaySession(Base):
    """表 3B：单次游玩历史明细表"""
    __tablename__ = "play_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)

    game: Mapped["Game"] = relationship(back_populates="sessions")


class AppStateSetting(Base):
    """表 4：软件状态记忆与全局配置键值表"""
    __tablename__ = "app_state_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)


class Collection(Base):
    """表 5：系列合集与用户自定义分组"""
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    collection_type: Mapped[str] = mapped_column(String(20), default="series")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=True
    )

    items: Mapped[list["CollectionItem"]] = relationship(
        back_populates="collection",
        cascade="all, delete-orphan",
        order_by="CollectionItem.position.asc(), CollectionItem.id.asc()",
    )


class CollectionItem(Base):
    """表 6：系列合集 ↔ 游戏 有序关联表（删除合集绝不删除游戏本体）"""
    __tablename__ = "collection_items"
    __table_args__ = (
        UniqueConstraint("collection_id", "game_id", name="uq_collection_items_collection_game"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, index=True)
    relation_label: Mapped[str] = mapped_column(String(32), default="")
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    collection: Mapped["Collection"] = relationship(back_populates="items")
    game: Mapped["Game"] = relationship(back_populates="collection_items")


class GameNote(Base):
    """表 7：作品总评 / 角色手记 / 随记（一对多 Markdown 长评）"""
    __tablename__ = "game_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True
    )
    note_type: Mapped[str] = mapped_column(String(20), default="work", index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    content_md: Mapped[str] = mapped_column(Text, default="")
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    game: Mapped["Game"] = relationship(back_populates="notes")
