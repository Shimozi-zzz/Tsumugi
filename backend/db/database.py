import logging
from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from backend.core.config import DATABASE_URL, ensure_data_dirs

logger = logging.getLogger("tsumugi.db")

ensure_data_dirs()

engine = create_async_engine(DATABASE_URL, echo=False, future=True)


@event.listens_for(engine.sync_engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


# 轻量级无损增量列迁移清单：(表名, 列名, 列 DDL)
_ADDITIVE_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("game_media_paths", "bgm_path", "VARCHAR(500) DEFAULT ''"),
    ("game_media_paths", "pv_remote_url", "VARCHAR(1024) DEFAULT ''"),
    ("game_media_paths", "pv_mode", "VARCHAR(20) DEFAULT 'none'"),
    ("game_media_paths", "bgm_remote_url", "VARCHAR(1024) DEFAULT ''"),
    ("game_media_paths", "bgm_mode", "VARCHAR(20) DEFAULT 'none'"),
    ("games", "bangumi_id", "VARCHAR(64) DEFAULT ''"),
    ("games", "series", "VARCHAR(120) DEFAULT ''"),
]


async def _apply_additive_migrations(conn: AsyncConnection) -> list[str]:
    """检查既有 SQLite 表结构，缺失列时以 ALTER TABLE ADD COLUMN 平滑补齐（幂等）"""
    applied: list[str] = []
    for table, column, ddl in _ADDITIVE_COLUMN_MIGRATIONS:
        rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
        existing = {row[1] for row in rows}
        if not rows or column in existing:
            continue
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        applied.append(f"{table}.{column}")
        logger.info("SQLite auto-migration: added column %s.%s", table, column)
    return applied


async def init_db() -> list[str]:
    from backend.db import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        return await _apply_additive_migrations(conn)
