"""Collection 收藏关系（P2 / ADR 0046）：表/回填/状态编辑/收藏时刻 Memory/接口"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import collections
from app.api.routes import router
from app.database import Base, ensure_schema, get_db
from app.models import Collection, Item, Memory, Review


def _ext_item(db, title="作品", source="bangumi", raw=None):
    it = Item(title=title, type="external_ref", source=source, content="x", raw_metadata=raw)
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


class TestModel:
    def test_collection_table_created_on_legacy_db(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path}/old.db")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, title VARCHAR(255), type VARCHAR(50), content TEXT, source VARCHAR(50))"))
        Base.metadata.create_all(bind=engine)
        ensure_schema(bind=engine)
        cols = {c["name"] for c in __import__("sqlalchemy").inspect(engine).get_columns("collections")}
        assert {"item_id", "status", "favorite", "added_at"}.issubset(cols)
        engine.dispose()


class TestBackfill:
    def test_backfill_creates_rows_and_migrates_status(self, db):
        it = _ext_item(db)
        # 模拟 Bangumi 导入的状态书评
        rev = Review(item_id=it.id, title="从 Bangumi 导入", content="",
                     status="看完", source="bangumi_collection")
        db.add(rev)
        db.commit()
        n = collections.backfill_collections(db.bind)
        assert n == 1
        col = db.get(Collection, it.id)
        assert col.status == "看完"  # 从 Review 迁移
        assert col.favorite == 0
        assert col.added_at == it.created_at
        # 幂等：再跑 0 新建；且不批量造收藏 Memory
        assert collections.backfill_collections(db.bind) == 0
        assert db.query(Memory).filter(Memory.source_type == "collection").count() == 0

    def test_backfill_local_items_untouched(self, db):
        it = Item(title="笔记", type="note", source="local", content="c")
        db.add(it); db.commit()
        assert collections.backfill_collections(db.bind) == 0
        assert db.get(Collection, it.id) is None


class TestOnCollect:
    def test_first_collect_creates_collection_and_memory(self, db):
        it = _ext_item(db)
        assert collections.on_collect(it, db) is True
        db.commit()
        col = db.get(Collection, it.id)
        assert col is not None and col.favorite == 0
        mem = db.query(Memory).filter(Memory.source_type == "collection", Memory.source_ref == it.id).one()
        assert mem.summary == "这一天，我把它带回了图书馆"
        assert mem.item_id == it.id
        # 再次收藏（re-save）：不重复生成 Memory
        assert collections.on_collect(it, db) is False
        assert db.query(Memory).filter(Memory.source_type == "collection").count() == 1


class TestSetCollection:
    def test_set_status_and_favorite(self, db):
        it = _ext_item(db)
        col = collections.set_collection(it.id, db=db, status="在看", favorite=True)
        assert col.status == "在看"
        assert col.favorite == 1
        # 清空状态
        col = collections.set_collection(it.id, db=db, status="")
        assert col.status is None
        # 非法状态
        with pytest.raises(ValueError):
            collections.set_collection(it.id, db=db, status="不存在的状态")


class TestApi:
    @pytest.fixture
    def client(self, db):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        def override_get_db():
            yield db
        app.dependency_overrides[get_db] = override_get_db
        return TestClient(app)

    def test_patch_collection_and_filter(self, client, db):
        it = _ext_item(db)
        r = client.patch(f"/api/items/{it.id}/collection", json={"status": "看完", "favorite": True})
        assert r.status_code == 200
        body = r.json()
        assert body["collection_status"] == "看完"
        assert body["favorite"] is True
        # 非法状态 400
        assert client.patch(f"/api/items/{it.id}/collection", json={"status": "x"}).status_code == 400
        # 筛选
        assert client.get("/api/items?collection_status=看完").json()["total"] == 1
        assert client.get("/api/items?collection_status=在看").json()["total"] == 0
        # detail 含收藏字段
        d = client.get(f"/api/items/{it.id}/detail").json()
        assert d["collection_status"] == "看完"
        assert d["collected_at"] is not None

    def test_list_collections_map(self, client, db):
        a = _ext_item(db, title="A")
        collections.set_collection(a.id, db=db, status="搁置")
        rows = client.get("/api/collections").json()
        assert {"item_id": a.id, "status": "搁置"} in rows
