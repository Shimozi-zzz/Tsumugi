"""数据库连接和会话管理"""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def ensure_schema(bind=None):
    """轻量迁移：create_all 只建新表，不会给已有表加列。
    对已存在的旧库补上新 ORM 列（item 外部字段、content_hash、chunk.review_id、
    chunk.source_type / chunk.connector）并回填 source_type。

    bind 供测试传入临时引擎；默认用全局 engine。"""
    engine = bind if bind is not None else globals()["engine"]
    insp = inspect(engine)
    if "items" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("items")}
        item_additions = {
            "content_hash": "VARCHAR(64)",
            "image_url": "VARCHAR(500)",
            "external_id": "VARCHAR(255)",
            "raw_metadata": "TEXT",
            "synced_at": "DATETIME",
            # P1 Work 模型世界轴列（ADR 0045）
            "work_type": "VARCHAR(20)",
            "alternative_title": "VARCHAR(255)",
            "release_date": "VARCHAR(20)",
        }
        with engine.begin() as conn:
            for col, ddl_type in item_additions.items():
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE items ADD COLUMN {col} {ddl_type}"))
    if "chunks" in insp.get_table_names():
        chunk_cols = {c["name"] for c in insp.get_columns("chunks")}
        chunk_additions = {}
        if "review_id" not in chunk_cols:
            chunk_additions["review_id"] = "INTEGER"
        if "memory_id" not in chunk_cols:
            chunk_additions["memory_id"] = "INTEGER"
        if "source_type" not in chunk_cols:
            chunk_additions["source_type"] = "VARCHAR(20)"
        if "connector" not in chunk_cols:
            chunk_additions["connector"] = "VARCHAR(50)"
        if chunk_additions:
            with engine.begin() as conn:
                for col, ddl_type in chunk_additions.items():
                    conn.execute(text(f"ALTER TABLE chunks ADD COLUMN {col} {ddl_type}"))
        _backfill_chunk_source_type(engine)
    if "reviews" in insp.get_table_names():
        review_cols = {c["name"] for c in insp.get_columns("reviews")}
        if "source" not in review_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE reviews ADD COLUMN source VARCHAR(20)"))
        if "font_size" not in review_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE reviews ADD COLUMN font_size INTEGER"))
    # reviews 表其余列由 create_all 负责（新表）
    # P3（ADR 0047）：memories 加 emotion 列（media 表由 create_all 建）
    if "memories" in insp.get_table_names():
        mem_cols = {c["name"] for c in insp.get_columns("memories")}
        if "emotion" not in mem_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE memories ADD COLUMN emotion VARCHAR(20)"))


def _backfill_chunk_source_type(engine):
    """给历史 chunk 回填 source_type（ADR 0025）：review→review；external_ref 条目
    自身内容→external_reference（并记 connector）；其余→note。幂等：只填 NULL。

    connector 仅 external_reference 需要；review/note 保持 NULL（避免混淆来源）。"""
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE chunks SET source_type = 'review' "
            "WHERE source_type IS NULL AND review_id IS NOT NULL"
        ))
        conn.execute(text(
            "UPDATE chunks SET source_type = 'external_reference', "
            "connector = (SELECT items.source FROM items WHERE items.id = chunks.item_id) "
            "WHERE source_type IS NULL AND item_id IN "
            "(SELECT id FROM items WHERE items.type = 'external_ref')"
        ))
        conn.execute(text(
            "UPDATE chunks SET source_type = 'note' WHERE source_type IS NULL"
        ))


def get_db():
    """FastAPI 依赖注入：请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
