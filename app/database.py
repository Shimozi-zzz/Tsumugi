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


def ensure_schema():
    """轻量迁移：create_all 只建新表，不会给已有表加列。
    对已存在的旧库补上新 ORM 列（item 外部字段、content_hash、chunk.review_id）。"""
    insp = inspect(engine)
    if "items" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("items")}
        item_additions = {
            "content_hash": "VARCHAR(64)",
            "image_url": "VARCHAR(500)",
            "external_id": "VARCHAR(255)",
            "raw_metadata": "TEXT",
            "synced_at": "DATETIME",
        }
        with engine.begin() as conn:
            for col, ddl_type in item_additions.items():
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE items ADD COLUMN {col} {ddl_type}"))
    if "chunks" in insp.get_table_names():
        chunk_cols = {c["name"] for c in insp.get_columns("chunks")}
        if "review_id" not in chunk_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE chunks ADD COLUMN review_id INTEGER"))
    if "reviews" in insp.get_table_names():
        review_cols = {c["name"] for c in insp.get_columns("reviews")}
        if "source" not in review_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE reviews ADD COLUMN source VARCHAR(20)"))
        if "font_size" not in review_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE reviews ADD COLUMN font_size INTEGER"))
    # reviews 表其余列由 create_all 负责（新表）


def get_db():
    """FastAPI 依赖注入：请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
