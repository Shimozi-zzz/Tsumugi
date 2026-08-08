"""ensure_schema 迁移测试：chunks 加 source_type/connector 列并回填历史值（ADR 0025）"""
import pytest
from sqlalchemy import create_engine, text

from app.database import ensure_schema


@pytest.fixture()
def old_engine(tmp_path):
    """构造旧版 schema（chunks 无 source_type/connector 列），带三类历史数据。"""
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE items (
                id INTEGER PRIMARY KEY, title VARCHAR(255), type VARCHAR(50),
                content TEXT, source VARCHAR(50), external_id VARCHAR(255)
            )
        """))
        conn.execute(text("""
            CREATE TABLE chunks (
                id INTEGER PRIMARY KEY, item_id INTEGER, review_id INTEGER,
                content TEXT, chunk_index INTEGER, embedding_ref VARCHAR(255)
            )
        """))
        conn.execute(text("""
            CREATE TABLE reviews (
                id INTEGER PRIMARY KEY, item_id INTEGER, title VARCHAR(255),
                content TEXT
            )
        """))
        conn.execute(text(
            "INSERT INTO items (id, title, type, content, source) "
            "VALUES (1, '笔记', 'note', 'x', 'local')"
        ))
        conn.execute(text(
            "INSERT INTO items (id, title, type, content, source, external_id) "
            "VALUES (2, '外部', 'external_ref', 'y', 'bangumi', '301')"
        ))
        conn.execute(text(
            "INSERT INTO items (id, title, type, content, source, external_id) "
            "VALUES (3, '萌娘', 'external_ref', 'z', 'moegirl', '42')"
        ))
        conn.execute(text(
            "INSERT INTO chunks (item_id, review_id, content, chunk_index, embedding_ref) "
            "VALUES (1, NULL, 'n1', 0, 'i1'), (2, NULL, 'e1', 0, 'i2'), (3, NULL, 'e2', 0, 'i3')"
        ))
        conn.execute(text(
            "INSERT INTO reviews (item_id, title, content) VALUES (1, 'r', 'c')"
        ))
        conn.execute(text(
            "INSERT INTO chunks (item_id, review_id, content, chunk_index, embedding_ref) "
            "VALUES (1, 1, 'r1', 0, 'i4')"
        ))
    yield engine
    engine.dispose()


class TestChunkSourceTypeMigration:
    def test_columns_added(self, old_engine):
        ensure_schema(bind=old_engine)
        with old_engine.connect() as conn:
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(chunks)")).fetchall()}
        assert {"source_type", "connector"}.issubset(cols)

    def test_backfills_source_type_and_connector(self, old_engine):
        ensure_schema(bind=old_engine)
        with old_engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT embedding_ref, source_type, connector FROM chunks ORDER BY id"
            )).fetchall()
        by_ref = {r[0]: (r[1], r[2]) for r in rows}
        # note 条目自身内容 → note，connector 留空
        assert by_ref["i1"] == ("note", None)
        # external_ref 条目 → external_reference，记来源 Connector
        assert by_ref["i2"] == ("external_reference", "bangumi")
        assert by_ref["i3"] == ("external_reference", "moegirl")
        # review 内容 → review，connector 留空（避免混淆来源）
        assert by_ref["i4"] == ("review", None)

    def test_idempotent_no_null_left(self, old_engine):
        ensure_schema(bind=old_engine)
        ensure_schema(bind=old_engine)  # 再跑一次不报错、不产生新的修改
        with old_engine.connect() as conn:
            nulls = conn.execute(text(
                "SELECT COUNT(*) FROM chunks WHERE source_type IS NULL"
            )).scalar()
        assert nulls == 0
