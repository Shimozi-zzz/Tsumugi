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

    def test_review_embedding_failure_rolls_back_memory(self, db, fake_collection, patch_embeddings, monkeypatch):
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


class TestOnThisDay:
    """跨年同月同日查询（Phase E 往年今日）：严格月日匹配 + 年份过滤 + 排序。"""

    def _mk(self, db, item, occurred, summary="s"):
        m = Memory(item_id=item.id, source_type="review", source_ref=1,
                   occurred_at=occurred, summary=summary)
        db.add(m)
        return m

    def test_strict_month_day_and_max_year(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        self._mk(db, item, datetime(2024, 8, 9, 10, 0), "两年前")
        self._mk(db, item, datetime(2022, 8, 9, 10, 0), "四年前")
        self._mk(db, item, datetime(2026, 8, 9, 10, 0), "今年")
        self._mk(db, item, datetime(2024, 7, 9, 10, 0), "不同月")
        self._mk(db, item, datetime(2024, 8, 1, 10, 0), "不同日")
        db.commit()
        rows = memories.query_on_this_day(db, month=8, day=9, max_year=2026)
        assert {r.summary for r in rows} == {"两年前", "四年前"}  # 严格 08-09 且 year<2026
        assert [r.occurred_at for r in rows] == sorted([r.occurred_at for r in rows], reverse=True)

    def test_max_year_none_includes_current(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        self._mk(db, item, datetime(2026, 8, 9, 10, 0), "今年")
        db.commit()
        assert len(memories.query_on_this_day(db, month=8, day=9)) == 1  # 不传 max_year 含今年
        assert memories.query_on_this_day(db, month=8, day=9, max_year=2026) == []

    def test_leap_day_strict(self, db, fake_collection, patch_embeddings):
        """2月29日：只在 2月29日当天命中（闰年才有），2月28日不前移匹配。"""
        item = _mk_item(db)
        self._mk(db, item, datetime(2024, 2, 29, 10, 0), "闰日记忆")
        self._mk(db, item, datetime(2020, 2, 29, 10, 0), "更早闰日")
        self._mk(db, item, datetime(2024, 2, 28, 10, 0), "普通日")
        db.commit()
        rows = memories.query_on_this_day(db, month=2, day=29, max_year=2026)
        assert {r.summary for r in rows} == {"闰日记忆", "更早闰日"}
        # 2月28日不匹配 2月29日
        assert {r.summary for r in memories.query_on_this_day(db, month=2, day=28, max_year=2026)} == {"普通日"}


class TestDirectMemory:
    """P3 / ADR 0047：轻量文字/里程碑 Memory 直接创建、情绪、媒体附件。"""

    def test_create_text_memory(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        mem = memories.create_direct_memory(item.id, "今天把这段重新看了一遍。", "text", emotion="感动", db=db)
        assert mem.source_type == "text"
        assert mem.emotion == "感动"
        assert mem.summary == "今天把这段重新看了一遍。"

    def test_create_milestone(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        mem = memories.create_direct_memory(item.id, "完成了这部作品。", "milestone", db=db)
        assert mem.source_type == "milestone"
        assert mem.emotion is None

    def test_invalid(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        with pytest.raises(ValueError):
            memories.create_direct_memory(item.id, "x", "review", db=db)  # review 不允许直接建
        with pytest.raises(ValueError):
            memories.create_direct_memory(item.id, "  ", "text", db=db)  # 空
        with pytest.raises(ValueError):
            memories.create_direct_memory(99999, "x", "text", db=db)

    def test_delete_direct_only(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        mem = memories.create_direct_memory(item.id, "一条轻量记录", "text", db=db)
        assert memories.delete_direct_memory(mem.id, db=db) is True
        # review 记忆不允许从这里删
        r = reviews.create_review(item.id, "书评内容" * 5, db=db)
        assert memories.delete_direct_memory(r.id, db=db) is False
        assert db.query(Memory).filter(Memory.source_type == "review").count() == 1

    def test_memory_vectors_indexed_and_retrievable(self, db, fake_collection, patch_embeddings):
        """P7 / ADR 0051：直接 Memory 内容写入向量（source_type=memory），可被语义检索到。"""
        from app.retrieval import retrieve_chunks
        from app.models import Chunk

        item = _mk_item(db, title="作品", content="原作内容" * 20)
        mem = memories.create_direct_memory(item.id, "孤独是常伴的，但也很安静。", "text", db=db)
        chunk_rows = db.query(Chunk).filter(Chunk.memory_id == mem.id).all()
        assert len(chunk_rows) >= 1
        assert chunk_rows[0].source_type == "memory"
        assert chunk_rows[0].embedding_ref.startswith("memory")
        # 语义检索命中（用与摘要一致的查询，假 embedding 下余弦=1 必排最前）
        hits = retrieve_chunks("孤独是常伴的，但也很安静。", top_k=5, db=db)
        assert any(h.source_type == "memory" and h.content and "孤独" in h.content for h in hits)
        # 删除 → 向量与 chunk 清除
        memories.delete_direct_memory(mem.id, db=db)
        assert db.query(Chunk).filter(Chunk.memory_id == mem.id).count() == 0
        assert not any(k.startswith(f"memory{mem.id}_") for k in fake_collection.vectors)

    def test_backfill_memory_vectors_idempotent(self, db, fake_collection, patch_embeddings):
        from app.models import Chunk

        item = _mk_item(db)
        mem = memories.create_direct_memory(item.id, "一条已有向量的记忆", "text", db=db)
        # 再跑 backfill → 0（已有向量）
        assert memories.backfill_memory_vectors(db.bind) == 0
        assert db.query(Chunk).filter(Chunk.memory_id == mem.id).count() >= 1


class TestMemoryVectorMetadata:
    """Phase 10-1-B-5：Memory 向量 metadata 补充 occurred_at / emotion / milestone。"""

    def _memory_metas(self, fake_collection, mem):
        return [fake_collection.metas[k] for k in fake_collection.vectors
                if k.startswith(f"memory{mem.id}_")]

    def test_metadata_includes_occurred_at_emotion(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, title="作品")
        mem = memories.create_direct_memory(item.id, "感动到说不出话。" + "还是想写点什么。" * 6, "text",
                                            emotion="感动", db=db)
        metas = self._memory_metas(fake_collection, mem)
        assert len(metas) >= 1
        for m in metas:
            assert m["occurred_at"], "occurred_at 应为 ISO 字符串"
            assert m["emotion"] == "感动"
            assert "milestone" not in m  # text 非 milestone
            # 既有键保留
            assert m["item_id"] == item.id and m["memory_id"] == mem.id
            assert m["source_type"] == "memory"

    def test_metadata_milestone_flag(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        mem = memories.create_direct_memory(item.id, "完成了这部作品。", "milestone", db=db)
        metas = self._memory_metas(fake_collection, mem)
        assert metas
        assert all(m.get("milestone") is True for m in metas)

    def test_metadata_none_and_multi_chunk_shared(self, db, fake_collection, patch_embeddings):
        """None/空不写该键且不失败；多 chunk 共享记忆级 metadata、chunk_index 各异。"""
        item = _mk_item(db, title="作品")
        mem = memories.create_direct_memory(item.id, ("这是一个很长的记忆片段，用于触发多个向量分块。" * 40), "text", db=db)  # 无 emotion
        metas = self._memory_metas(fake_collection, mem)
        assert len(metas) > 1
        for m in metas:
            assert "emotion" not in m
            assert "occurred_at" in m
        assert len({m["occurred_at"] for m in metas}) == 1  # 共享
        assert len({m["chunk_index"] for m in metas}) == len(metas)

    def test_review_vector_metadata_does_not_invent_signals(self, db, fake_collection, patch_embeddings):
        """Review 无 occurred_at/emotion/milestone 字段 → 向量 metadata 不新增这些键。"""
        from app import reviews
        item = _mk_item(db)
        r = reviews.create_review(item.id, "这部作品让我想起了很多。" * 6, db=db)
        metas = [fake_collection.metas[k] for k in fake_collection.vectors
                 if k.startswith(f"review{r.id}_")]
        assert metas
        for m in metas:
            assert "occurred_at" not in m and "emotion" not in m and "milestone" not in m
            assert m["source_type"] == "review" and m["review_id"] == r.id


class TestApiMemory:
    """P3：直接 Memory 的 API（含媒体上传）。"""

    @pytest.fixture
    def client(self, db, fake_collection, patch_embeddings):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        def override_get_db():
            yield db
        app.dependency_overrides[get_db] = override_get_db
        return TestClient(app)

    def test_create_with_emotion_and_media(self, client, db):
        item = _mk_item(db)
        r = client.post(f"/api/items/{item.id}/memories",
                        data={"summary": "一张截图记下这一刻", "source_type": "text", "emotion": "治愈"},
                        files={"file": ("shot.png", b"\x89PNG\r\n\x1a\nfakeimage", "image/png")})
        assert r.status_code == 200
        body = r.json()
        assert body["emotion"] == "治愈"
        assert len(body["media"]) == 1
        assert body["media"][0]["url"].startswith("/static/uploads/")
        # 真实文件已写入 upload_dir（内存库下路径存在与否不校验，校验 DB 记录）
        from app.models import Media
        media = db.query(Media).filter(Media.memory_id == body["id"]).one()
        assert media.media_type == "image"
        assert media.size == len(b"\x89PNG\r\n\x1a\nfakeimage")

    def test_create_validation_and_delete(self, client, db):
        item = _mk_item(db)
        assert client.post(f"/api/items/{item.id}/memories", data={"summary": "x", "source_type": "bad"}).status_code == 400
        r = client.post(f"/api/items/{item.id}/memories", data={"summary": "一条里程碑", "source_type": "milestone"})
        assert r.status_code == 200
        assert client.delete(f"/api/memories/{r.json()['id']}").json()["deleted"] == r.json()["id"]
        assert client.get(f"/api/items/{item.id}/memories").json() == []

    def test_list_includes_emotion(self, client, db):
        item = _mk_item(db)
        client.post(f"/api/items/{item.id}/memories", data={"summary": "有点怀念", "source_type": "text", "emotion": "怀念"})
        rows = client.get(f"/api/items/{item.id}/memories").json()
        assert rows[0]["emotion"] == "怀念"


class TestSearchMy:
    """P6 / ADR 0050：个人全文检索（作品/书评/记忆）。"""

    @pytest.fixture
    def client(self, db, fake_collection, patch_embeddings):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        def override_get_db():
            yield db
        app.dependency_overrides[get_db] = override_get_db
        return TestClient(app)

    def test_search_all_groups(self, client, db, fake_collection, patch_embeddings):
        item = _mk_item(db, title="孤独笔记", content="关于孤独的一点想法。")
        r = reviews.create_review(item.id, "孤独是常伴的。", title="孤独有感", db=db)
        mem = memories.create_direct_memory(item.id, "今天又想起孤独的话题", "text", db=db)
        body = client.get("/api/search/my", params={"q": "孤独"}).json()
        assert any(w["title"] == "孤独笔记" for w in body["works"])
        assert any(rev["title"] == "孤独有感" for rev in body["reviews"])
        assert any(m["id"] == mem.id for m in body["memories"])
        assert client.get("/api/search/my", params={"q": ""}).json() == {"works": [], "reviews": [], "memories": []}
        assert client.get("/api/search/my", params={"q": "不存在的词xyz"}).json() == {"works": [], "reviews": [], "memories": []}

    def test_memories_search_text_filter(self, client, db, fake_collection, patch_embeddings):
        item = _mk_item(db)
        memories.create_direct_memory(item.id, "夏天的蝉鸣", "text", db=db)
        memories.create_direct_memory(item.id, "冬天的雪", "text", db=db)
        rows = client.get("/api/memories", params={"search": "蝉鸣"}).json()
        assert len(rows) == 1
        assert rows[0]["summary"] == "夏天的蝉鸣"


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
        r = reviews.create_review(item.id, "新书评内容" * 5, db=db)
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

    def test_api_on_this_day(self, client, db, fake_collection, patch_embeddings):
        item = _mk_item(db, title="命运石之门")
        m = Memory(item_id=item.id, source_type="review", source_ref=1,
                   occurred_at=datetime(2024, 8, 9, 10, 0), summary="两年前的今天")
        db.add(m)
        db.commit()
        rows = client.get("/api/memories?month=8&day=9&max_year=2026").json()
        assert len(rows) == 1
        assert rows[0]["summary"] == "两年前的今天"
        assert rows[0]["item_title"] == "命运石之门"
        # 不传 month/day → 走原全局查询（Phase C 兼容），max_year 参数被忽略
        assert len(client.get("/api/memories?max_year=2026").json()) == 1

    def test_api_item_not_found(self, client):
        assert client.get("/api/items/9999/memories").status_code == 404
