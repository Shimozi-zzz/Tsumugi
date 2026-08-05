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
    对已存在的旧库补上新 ORM 列/表（item 外部字段、content_hash、sources 表）。"""
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
    # sources 表由 create_all 负责（新表），这里仅确保幂等提示
    if "sources" not in insp.get_table_names():
        pass  # create_all 会创建


def get_db():
    """FastAPI 依赖注入：请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
