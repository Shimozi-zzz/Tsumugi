"""Work 模型世界轴列（P1 / ADR 0045）：提炼/回填/筛选/手动编辑"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import work_model
from app.api.routes import router
from app.database import Base, ensure_schema, get_db
from app.ingest import ingest_external
from app.models import Item

BANGUMI_RAW = {
    "source": "bangumi",
    "detail": {
        "title": "剧场版 空之境界 痛觉残留",
        "description": "简介",
        "image_url": None,
        "metadata": {"original_name": "空の境界 劇場版 痛覚残留", "date": "2008-02-09",
                     "rating": 7.9, "type": 2, "tags": [], "characters": []},
    },
}
MOEGIRL_RAW = {"source": "moegirl", "detail": {
    "title": "初音未来", "description": "x", "image_url": None,
    "metadata": {"categories": ["VOCALOID角色"], "length": 100},
}}


class TestExtract:
    def test_bangumi_mapping(self):
        cols = work_model.extract_work_columns(BANGUMI_RAW)
        assert cols["work_type"] == "anime"       # type=2 → anime
        assert cols["alternative_title"] == "空の境界 劇場版 痛覚残留"
        assert cols["release_date"] == "2008-02-09"

    def test_bangumi_type_variants(self):
        for bt, wt in [(4, "game"), (1, "manga"), (3, "other"), (6, "other"), (999, None)]:
            raw = {"detail": {"metadata": {"type": bt}}}
            assert work_model.extract_work_columns(raw).get("work_type") == wt

    def test_no_type_source_returns_empty(self):
        assert work_model.extract_work_columns(MOEGIRL_RAW) == {}
        assert work_model.extract_work_columns(None) == {}
        assert work_model.extract_work_columns({"detail": {}}) == {}


class TestBackfill:
    def test_backfill_fills_and_is_idempotent(self, db):
        it = Item(title="空之境界", type="external_ref", source="bangumi",
                  content="x", raw_metadata=BANGUMI_RAW)
        db.add(it); db.commit()
        n = work_model.backfill_work_columns(db.bind)
        assert n == 1
        db.refresh(it)
        assert it.work_type == "anime"
        assert it.alternative_title == "空の境界 劇場版 痛覚残留"
        assert it.release_date == "2008-02-09"
        # 幂等：再跑 0 变更
        assert work_model.backfill_work_columns(db.bind) == 0

    def test_backfill_does_not_overwrite_user_value(self, db):
        it = Item(title="空之境界", type="external_ref", source="bangumi",
                  content="x", raw_metadata=BANGUMI_RAW, work_type="galgame")
        db.add(it); db.commit()
        n = work_model.backfill_work_columns(db.bind)
        db.refresh(it)
        assert it.work_type == "galgame"  # 用户值不被覆盖
        # 但 NULL 的别名/发行仍会回填（n≥1），再跑一次幂等为 0
        assert n >= 1
        assert it.alternative_title == "空の境界 劇場版 痛覚残留"
        assert work_model.backfill_work_columns(db.bind) == 0

    def test_local_items_untouched(self, db):
        it = Item(title="笔记", type="note", source="local", content="c")
        db.add(it); db.commit()
        assert work_model.backfill_work_columns(db.bind) == 0

    def test_ensure_schema_adds_columns(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path}/old.db")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, title VARCHAR(255), type VARCHAR(50), content TEXT, source VARCHAR(50))"))
        ensure_schema(bind=engine)
        cols = {c["name"] for c in __import__("sqlalchemy").inspect(engine).get_columns("items")}
        assert {"work_type", "alternative_title", "release_date"}.issubset(cols)
        engine.dispose()


class TestApi:
    @pytest.fixture
    def client(self, db):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        def override_get_db():
            yield db
        app.dependency_overrides[get_db] = override_get_db
        return TestClient(app)

    def test_filter_and_detail(self, client, db):
        it = Item(title="空之境界", type="external_ref", source="bangumi",
                  content="x", raw_metadata=BANGUMI_RAW, work_type="anime",
                  alternative_title="空の境界 劇場版 痛覚残留", release_date="2008-02-09")
        db.add(it); db.commit()
        rows = client.get("/api/items?work_type=anime").json()
        assert rows["total"] == 1
        assert rows["items"][0]["work_type"] == "anime"
        assert rows["items"][0]["alternative_title"] == "空の境界 劇場版 痛覚残留"
        assert client.get("/api/items?work_type=game").json()["total"] == 0
        d = client.get(f"/api/items/{it.id}/detail").json()
        assert d["work_type"] == "anime"
        assert d["release_date"] == "2008-02-09"

    def test_patch_work_columns(self, client, db):
        it = Item(title="空之境界", type="external_ref", source="bangumi", content="x")
        db.add(it); db.commit()
        r = client.patch(f"/api/items/{it.id}/work", json={"work_type": "galgame"})
        assert r.status_code == 200
        assert r.json()["work_type"] == "galgame"
        # 非法枚举 → 400
        assert client.patch(f"/api/items/{it.id}/work", json={"work_type": "anime_xxx"}).status_code == 400
        # 清空
        r = client.patch(f"/api/items/{it.id}/work", json={"work_type": "", "release_date": "2020-01-01"})
        assert r.json()["work_type"] is None
        assert r.json()["release_date"] == "2020-01-01"
        # 不存在 → 404
        assert client.patch("/api/items/99999/work", json={"work_type": "anime"}).status_code == 404
