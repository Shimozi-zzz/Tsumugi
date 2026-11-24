import logging
from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
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
    ("games", "rating_overall", "REAL"),
    ("games", "rating_dimensions", "JSON"),
    ("games", "short_review", "TEXT DEFAULT ''"),
    ("collections", "description", "TEXT DEFAULT ''"),
    ("collections", "collection_type", "VARCHAR(20) DEFAULT 'series'"),
    ("collections", "updated_at", "DATETIME"),
]


async def _apply_additive_migrations(conn: AsyncConnection) -> list[str]:
    """检查既有 SQLite 表结构，缺失列时以 ALTER TABLE ADD COLUMN 平滑补齐并平滑迁移旧关联表（幂等）"""
    applied: list[str] = []
    for table, column, ddl in _ADDITIVE_COLUMN_MIGRATIONS:
        rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
        existing = {row[1] for row in rows}
        if not rows or column in existing:
            continue
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        applied.append(f"{table}.{column}")
        logger.info("SQLite auto-migration: added column %s.%s", table, column)

    # 归一化历史默认空值，防止老库空值引发序列化差异
    await conn.execute(
        text(
            "UPDATE games SET short_review = '' WHERE short_review IS NULL"
        )
    )
    await conn.execute(
        text(
            "UPDATE collections SET description = '' WHERE description IS NULL"
        )
    )
    await conn.execute(
        text(
            "UPDATE collections SET collection_type = 'series' "
            "WHERE collection_type IS NULL OR TRIM(collection_type) = ''"
        )
    )
    await conn.execute(
        text(
            "UPDATE collections SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP) "
            "WHERE updated_at IS NULL"
        )
    )

    # 平滑迁移老库 collection_games → collection_items（保留原有全部关联关系并分配连续 position）
    legacy_table = (
        await conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='collection_games'"
            )
        )
    ).fetchone()
    if legacy_table is not None:
        legacy_rows = (
            await conn.execute(
                text(
                    "SELECT cg.collection_id, cg.game_id "
                    "FROM collection_games cg "
                    "INNER JOIN collections c ON c.id = cg.collection_id "
                    "INNER JOIN games g ON g.id = cg.game_id "
                    "ORDER BY cg.collection_id ASC, cg.game_id ASC"
                )
            )
        ).fetchall()
        if legacy_rows:
            existing_pairs = {
                (int(r[0]), int(r[1]))
                for r in (
                    await conn.execute(
                        text("SELECT collection_id, game_id FROM collection_items")
                    )
                ).fetchall()
            }
            next_pos_map: dict[int, int] = {}
            pos_rows = (
                await conn.execute(
                    text(
                        "SELECT collection_id, COALESCE(MAX(position), -1) + 1 "
                        "FROM collection_items GROUP BY collection_id"
                    )
                )
            ).fetchall()
            for cid, next_p in pos_rows:
                next_pos_map[int(cid)] = int(next_p)

            migrated_count = 0
            for cid_raw, gid_raw in legacy_rows:
                cid, gid = int(cid_raw), int(gid_raw)
                if (cid, gid) in existing_pairs:
                    continue
                pos = next_pos_map.get(cid, 0)
                next_pos_map[cid] = pos + 1
                await conn.execute(
                    text(
                        "INSERT OR IGNORE INTO collection_items "
                        "(collection_id, game_id, position, relation_label, added_at) "
                        "VALUES (:cid, :gid, :pos, '', CURRENT_TIMESTAMP)"
                    ),
                    {"cid": cid, "gid": gid, "pos": pos},
                )
                existing_pairs.add((cid, gid))
                migrated_count += 1
            if migrated_count > 0:
                applied.append(f"collection_games->collection_items({migrated_count})")
                logger.info(
                    "SQLite auto-migration: migrated %d rows from collection_games to collection_items",
                    migrated_count,
                )

        await conn.execute(text("DROP TABLE IF EXISTS collection_games"))
        applied.append("drop:collection_games")

    return applied


async def init_db(target_engine: AsyncEngine | None = None) -> list[str]:
    from backend.db import models  # noqa: F401

    active_engine = target_engine or engine
    async with active_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        return await _apply_additive_migrations(conn)
