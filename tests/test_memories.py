"""Memory 记忆核心测试（Phase A / ADR 0041）

覆盖：Review 创建自动生成 Memory、编辑同步摘要、删除级联删除、
按 item 查询、全局筛选、迁移建表、API 端点。
"""
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import memories, reviews
from app.database import Base, ensure_schema
from app.ingest import ingest_text_document
from app.models import Item, Memory, Review
from app.api.routes import router
from app.database import get_db


def _mk_item(db, title="作品", content="原作内容" * 20, **kw):
    return ingest_text_document(title, content, db=db, **kw)


class TestMigration:
    def test_create_all_builds_memories_table_on_legacy_db(self, tmp_path):
        """旧库（无 memories 表）在启动 create_all + ensure_schema 后获得新表。"""
        engine = create_engine(f"sqlite:///{tmp_path}/old.db")
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE items (
                    id INTEGER PRIMARY KEY, title VARCHAR(255), type VARCHAR(50),
                    content TEXT, source VARCHAR(50)
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
        Base.metadata.create_all(bind=engine)  # 同 main.py 启动逻辑
        ensure_schema(bind=engine)
        insp = __import__("sqlalchemy").inspect(engine)
        cols = {c["name"] for c in insp.get_columns("memories")}
        assert {"id", "item_id", "source_type", "source_ref",
                "occurred_at", "summary", "created_at"}.issubset(cols)
        engine.dispose()


class TestReviewCreateAutoMemory:
    def test_create_review_generates_memory(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        r = reviews.create_review(item.id, "这部作品让我想起了很多。" * 10, db=db)
        mem = db.query(Memory).filter(
            Memory.source_type == "review", Memory.source_ref == r.id
        ).one()
        assert mem.item_id == item.id
        assert mem.source_type == "review"
        assert mem.source_ref == r.id
        assert mem.occurred_at == r.created_at  # 与 Review 创建时间一致
        assert mem.summary

    def test_summary_prefers_title(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        r = reviews.create_review(item.id, "内容很长很长的正文。", title="完结感想", db=db)
        mem = db.query(Memory).filter(Memory.source_ref == r.id).one()
        assert mem.summary == "完结感想"

    def test_summary_falls_back_to_truncated_content(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        long = "这是一段" * 40
        r = reviews.create_review(item.id, long, db=db)
        mem = db.query(Memory).filter(Memory.source_ref == r.id).one()
        assert mem.summary.startswith("这是一段")
        assert len(mem.summary) <= 41  # 40 字 + 省略号
        assert mem.summary.endswith("…")

    def test_review_embedding_failure_rolls_back_memory(self, db, fake_collection, monkeypatch):
        from app.embeddings import EmbeddingError
        item = _mk_item(db)
        def boom(texts):
            raise EmbeddingError("模型挂了")
        monkeypatch.setattr("app.embeddings.embed_texts", boom)
        with pytest.raises(EmbeddingError):
            reviews.create_review(item.id, "很长的内容" * 30, db=db)
        assert db.query(Review).count() == 0
        assert db.query(Memory).count() == 0  # 与 Review 同事务回滚


class TestReviewEditSync:
    def test_content_edit_syncs_summary(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        r = reviews.create_review(item.id, "第一版内容" * 6, db=db)
        mem0 = db.query(Memory).filter(Memory.source_ref == r.id).one()
        assert "第一版内容" in mem0.summary
        reviews.update_review(r.id, content="第二版完全不同的感想内容" * 10, db=db)
        db.refresh(mem0)
        assert "第二版完全不同的感想内容" in mem0.summary

    def test_title_edit_syncs_summary(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        r = reviews.create_review(item.id, "正文" * 10, db=db)
        reviews.update_review(r.id, title="新标题", db=db)
        mem = db.query(Memory).filter(Memory.source_ref == r.id).one()
        assert mem.summary == "新标题"

    def test_meta_only_edit_keeps_summary(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        r = reviews.create_review(item.id, "正文内容" * 8, title="原标题", db=db)
        reviews.update_review(r.id, rating=8, status="看完", db=db)
        mem = db.query(Memory).filter(Memory.source_ref == r.id).one()
        assert mem.summary == "原标题"

    def test_update_review_without_memory_is_noop(self, db, fake_collection, patch_embeddings):
        """不走 create_review 的 Review（如 Bangumi 导入）编辑时不应凭空造 Memory。"""
        item = _mk_item(db)
        direct = Review(item_id=item.id, content="", title="从 Bangumi 导入")
        db.add(direct)
        db.commit()
        assert db.query(Memory).count() == 0
        reviews.update_review(direct.id, title="从 Bangumi 导入（改）", db=db)
        assert db.query(Memory).count() == 0


class TestReviewDelete:
    def test_delete_review_removes_memory(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        r = reviews.create_review(item.id, "要删除的书评内容" * 8, db=db)
        assert db.query(Memory).filter(Memory.source_ref == r.id).count() == 1
        assert reviews.delete_review(r.id, db=db) is True
        assert db.query(Memory).filter(Memory.source_ref == r.id).count() == 0
        assert db.query(Review).filter(Review.id == r.id).count() == 0


class TestBackfill:
    def test_backfills_existing_reviews_idempotent(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, content="内容A" * 20)
        # 模拟存量 Review（不走 create_review，无 Memory）
        old = Review(item_id=item.id, title="旧书评", content="旧内容" * 20)
        db.add(old)
        db.commit()
        assert db.query(Memory).count() == 0

        n = memories.backfill_reviews(db.bind)
        assert n == 1
        mem = db.query(Memory).filter(Memory.source_ref == old.id).one()
        assert mem.source_type == "review"
        assert mem.summary == "旧书评"
        assert mem.occurred_at == old.created_at

        # 幂等：再跑不重复建
        assert memories.backfill_reviews(db.bind) == 0
        assert db.query(Memory).count() == 1

    def test_backfill_skips_reviews_already_having_memory(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, content="内容B" * 20)
        r = reviews.create_review(item.id, "新书评内容" * 5, db=db)  # 已有 Memory
        assert memories.backfill_reviews(db.bind) == 0
        assert db.query(Memory).filter(Memory.source_ref == r.id).count() == 1

    def test_backfill_falls_back_to_truncated_content_summary(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, content="内容C" * 20)
        old = Review(item_id=item.id, title="", content="很长的一段旧感想" * 30)
        db.add(old)
        db.commit()
        memories.backfill_reviews(db.bind)
        mem = db.query(Memory).filter(Memory.source_ref == old.id).one()
        assert mem.summary.startswith("很长的一段旧感想")
        assert mem.summary.endswith("…")


class TestQueries:
    def test_list_item_memories_ordered_desc(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        r1 = reviews.create_review(item.id, "第一次记录" * 6, db=db)
        r2 = reviews.create_review(item.id, "第二次记录" * 6, db=db)
        # 固定 occurred_at 以便断言排序（默认 created_at 很近）
        t1, t2 = datetime(2026, 1, 1), datetime(2026, 6, 1)
        db.query(Memory).filter(Memory.source_ref == r1.id).update({"occurred_at": t1})
        db.query(Memory).filter(Memory.source_ref == r2.id).update({"occurred_at": t2})
        db.commit()
        mems = memories.list_item_memories(item.id, db=db)
        assert [m.source_ref for m in mems] == [r2.id, r1.id]  # 最新在前

    def test_query_global_item_filter(self, db, fake_collection, patch_embeddings):
        a = _mk_item(db, title="A", content="关于作品A的内容" * 10)
        b = _mk_item(db, title="B", content="关于作品B的内容" * 10)  # 内容不同，避免 hash 去重
        reviews.create_review(a.id, "关于A的记录" * 5, db=db)
        reviews.create_review(b.id, "关于B的记录" * 5, db=db)
        rows = memories.query_memories(db, item_id=a.id)
        assert len(rows) == 1
        assert rows[0].item_id == a.id

    def test_query_time_range(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        r1 = reviews.create_review(item.id, "一月" * 5, db=db)
        r2 = reviews.create_review(item.id, "三月" * 5, db=db)
        r3 = reviews.create_review(item.id, "六月" * 5, db=db)
        for ref, dt in [(r1.id, datetime(2026, 1, 10)), (r2.id, datetime(2026, 3, 10)),
                        (r3.id, datetime(2026, 6, 10))]:
            db.query(Memory).filter(Memory.source_ref == ref).update({"occurred_at": dt})
        db.commit()
        # 时间范围 [2026-02-01, 2026-12-31)
        rows = memories.query_memories(db, start="2026-02-01", end="2026-12-31")
        assert {m.source_ref for m in rows} == {r2.id, r3.id}
        # 纯日期 end 按当日结束（exclusive）
        rows = memories.query_memories(db, start="2026-01-01", end="2026-03-10")
        assert {m.source_ref for m in rows} == {r1.id, r2.id}  # r3(6/10) 不在

    def test_query_skip_limit(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        ids = [reviews.create_review(item.id, f"第{i}次" * 4, db=db).id for i in range(5)]
        # occurred_at 相同秒内创建 → 次要排序按 id 倒序：ids[4..0]
        rows = memories.query_memories(db, skip=2, limit=2)
        assert len(rows) == 2
        assert {m.source_ref for m in rows} == {ids[1], ids[2]}


class TestApi:
    @pytest.fixture
    def client(self, db, fake_collection, patch_embeddings):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        def override_get_db():
            yield db
        app.dependency_overrides[get_db] = override_get_db
        return TestClient(app)

    def test_api_crud_flow(self, client, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        # 创建书评（无标题 → 摘要取内容）→ 生成 Memory
        r = client.post(f"/api/items/{item.id}/reviews",
                        json={"content": "这是 API 创建的书评。"})
        assert r.status_code == 200
        mems = client.get(f"/api/items/{item.id}/memories").json()
        assert len(mems) == 1
        assert mems[0]["source_type"] == "review"
        assert mems[0]["summary"] == "这是 API 创建的书评。"
        assert mems[0]["item_title"] == "作品"
        rev_id = mems[0]["source_ref"]

        # 编辑内容 → Memory 摘要同步；补标题 → 摘要改为标题（标题优先）
        client.patch(f"/api/reviews/{rev_id}", json={"content": "改过的内容。"})
        assert client.get(f"/api/items/{item.id}/memories").json()[0]["summary"] == "改过的内容。"
        client.patch(f"/api/reviews/{rev_id}", json={"title": "改后标题"})
        assert client.get(f"/api/items/{item.id}/memories").json()[0]["summary"] == "改后标题"

        # 全局查询
        g = client.get("/api/memories?item_id={}".format(item.id)).json()
        assert len(g) == 1

        # 删除 → Memory 级联删除
        client.delete(f"/api/reviews/{rev_id}")
        assert client.get(f"/api/items/{item.id}/memories").json() == []

    def test_api_global_filter_by_time(self, client, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        r = reviews.create_review(item.id, "很久以前的记录" * 5, db=db)
        db.query(Memory).filter(Memory.source_ref == r.id).update(
            {"occurred_at": datetime(2024, 5, 1)})
        db.commit()
        rows = client.get("/api/memories?start=2023&end=2025").json()
        assert len(rows) == 1
        assert client.get("/api/memories?start=2026").json() == []

    def test_api_item_not_found(self, client):
        assert client.get("/api/items/9999/memories").status_code == 404
