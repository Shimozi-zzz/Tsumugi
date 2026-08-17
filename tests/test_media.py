"""Phase 11-B：统一作品实体 MediaEntry / MediaSource 测试。

覆盖：migration、MediaSource 唯一性、Item 兼容、Bangumi+AniList 合并、
anime/manga 与不同年份不误并、字段级 fallback、raw_metadata 保留、
收藏入库后自动建立 Media / MediaSource、/media/{id} 聚合详情。
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app import media as media_svc
from app.api.routes import router
from app.database import Base, ensure_schema, get_db
from app.models import Item, MediaEntry, MediaSource


@pytest.fixture(scope="function")
def client(db, fake_collection, patch_embeddings):
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _mk_item(db, **kw):
    defaults = dict(title="作品", type="external_ref", source="bangumi", external_id="1", content="")
    defaults.update(kw)
    it = Item(**defaults)
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


class TestMigration:
    def test_migration_adds_media_id_and_tables(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path}/old.db")
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE items (id INTEGER PRIMARY KEY, title VARCHAR(255), "
                "type VARCHAR(50), content TEXT, source VARCHAR(50))"
            ))
        Base.metadata.create_all(bind=engine)
        ensure_schema(bind=engine)
        cols = {c["name"] for c in inspect(engine).get_columns("items")}
        assert "media_id" in cols  # 兼容列已补
        assert "media_entries" in inspect(engine).get_table_names()
        assert "media_sources" in inspect(engine).get_table_names()
        # 旧数据可读（兼容迁移不破坏已有 Item）
        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM items")).scalar() == 0
        engine.dispose()


class TestEnsure:
    def test_creates_entry_and_source_links_item(self, db):
        item = _mk_item(
            db, source="anilist", external_id="9253", title="Steins;Gate",
            alternative_title="シュタインズ・ゲート", work_type="anime",
            release_date="2011-04-05",
            raw_metadata={"source": "anilist", "detail": {"metadata": {
                "genres": ["Sci-Fi"], "status": "FINISHED", "episodes": 24,
                "background": "https://x/b.png", "staff": [], "relations": [],
            }}},
        )
        entry = media_svc.ensure_media_for_item(item, db)
        db.commit()
        assert entry is not None
        assert entry.canonical_title == "Steins;Gate"
        assert entry.work_type == "anime"
        assert entry.year == 2011
        assert json.loads(entry.genres) == ["Sci-Fi"]
        assert entry.status == "FINISHED"
        assert entry.episodes == 24
        assert entry.background == "https://x/b.png"
        # MediaSource 唯一 + item 关联 + raw_metadata 保留
        ms = db.query(MediaSource).filter(
            MediaSource.source == "anilist", MediaSource.external_id == "9253").first()
        assert ms is not None
        assert ms.media_id == entry.id
        assert item.media_id == entry.id
        assert ms.raw_metadata == item.raw_metadata
        # 幂等
        entry2 = media_svc.ensure_media_for_item(item, db)
        db.commit()
        assert entry2.id == entry.id
        assert db.query(MediaSource).count() == 1

    def test_local_item_skipped(self, db):
        item = _mk_item(db, source="local", external_id=None, type="note")
        assert media_svc.ensure_media_for_item(item, db) is None


class TestMerge:
    def test_bangumi_anilist_merge(self, db):
        b = _mk_item(db, source="bangumi", external_id="123", title="命运石之门",
                     alternative_title="STEINS;GATE", release_date="2011-04-05",
                     raw_metadata={"source": "bangumi", "detail": {"metadata": {"date": "2011-04-05"}}})
        a = _mk_item(db, source="anilist", external_id="9253", title="Steins;Gate",
                     work_type="anime", release_date="2011-04-05",
                     raw_metadata={"source": "anilist", "detail": {"metadata": {"genres": ["Sci-Fi"]}}})
        e1 = media_svc.ensure_media_for_item(b, db)
        e2 = media_svc.ensure_media_for_item(a, db)
        db.commit()
        assert e1.id == e2.id  # 同一作品合并为一个 MediaEntry
        assert db.query(MediaSource).count() == 2
        # 聚合详情：多来源
        detail = media_svc.media_detail(e1.id, db)
        assert len(detail["sources"]) == 2
        assert {s["source"] for s in detail["sources"]} == {"bangumi", "anilist"}
        assert detail["genres"] == ["Sci-Fi"]  # AniList 补全

    def test_anime_vs_manga_not_merged(self, db):
        a = _mk_item(db, source="anilist", external_id="9253", title="Steins;Gate",
                     work_type="anime", release_date="2011-04-05")
        m = _mk_item(db, source="anilist", external_id="47517", title="Steins;Gate",
                     work_type="manga", release_date="2009-10-23")
        e1 = media_svc.ensure_media_for_item(a, db)
        e2 = media_svc.ensure_media_for_item(m, db)
        db.commit()
        assert e1.id != e2.id  # 类型族不同不合并

    def test_different_year_not_merged(self, db):
        a = _mk_item(db, source="bangumi", external_id="1", title="作品", release_date="2011-01-01")
        b = _mk_item(db, source="anilist", external_id="2", title="作品", release_date="2018-01-01")
        e1 = media_svc.ensure_media_for_item(a, db)
        e2 = media_svc.ensure_media_for_item(b, db)
        db.commit()
        assert e1.id != e2.id  # 年份差 >1 不合并（防续作/重制误并）

    def test_field_fallback_across_sources(self, db):
        a = _mk_item(db, source="bangumi", external_id="1", title="作品", image_url="https://a.jpg",
                     raw_metadata={"source": "bangumi", "detail": {"metadata": {"description": "简介A"}}})
        b = _mk_item(db, source="anilist", external_id="2", title="作品",
                     raw_metadata={"source": "anilist", "detail": {"metadata": {"genres": ["科幻"]}}})
        e1 = media_svc.ensure_media_for_item(a, db)
        e2 = media_svc.ensure_media_for_item(b, db)
        db.commit()
        assert e1.id == e2.id
        assert e1.image_url == "https://a.jpg"  # Bangumi 封面
        assert json.loads(e1.genres) == ["科幻"]  # AniList genres 补全
        assert e1.description == "简介A"


class TestRoutes:
    def test_save_external_creates_media(self, client, db, monkeypatch):
        from app.connectors.base import ConnectorManifest, ItemDetail

        class FakeConn:
            name = "bangumi"
            manifest = ConnectorManifest(
                name="bangumi", display_name="Bangumi", version="0.1.0",
                capabilities=["search", "get_detail"],
            )

            def get_detail(self, external_id):
                return ItemDetail(
                    source="bangumi", title="命运石之门", external_id="123",
                    description="简介", image_url="https://x/a.jpg",
                    metadata={"date": "2011-04-05", "rating": 8.9, "tags": ["科幻"],
                              "genres": ["科幻"], "status": "FINISHED", "episodes": 24,
                              "characters": [], "staff": [], "relations": []},
                )

        monkeypatch.setattr("app.api.routes.connector_registry.get_connector",
                            lambda name: FakeConn())
        resp = client.post("/api/items/save-external",
                           json={"source": "bangumi", "external_id": "123", "title": "命运石之门"})
        assert resp.status_code == 200
        item_id = resp.json()["item_id"]
        it = db.get(Item, item_id)
        assert it.media_id is not None
        assert db.query(MediaSource).filter_by(source="bangumi", external_id="123").count() == 1
        entry = db.get(MediaEntry, it.media_id)
        assert entry.status == "FINISHED"

    def test_media_detail_route(self, client, db):
        item = _mk_item(db, source="anilist", external_id="9253", title="Steins;Gate",
                        work_type="anime", release_date="2011-04-05")
        entry = media_svc.ensure_media_for_item(item, db)
        db.commit()
        resp = client.get(f"/api/media/{entry.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["canonical_title"] == "Steins;Gate"
        assert data["year"] == 2011
        assert len(data["sources"]) == 1
        assert data["sources"][0]["source"] == "anilist"
        assert len(data["items"]) == 1

    def test_media_detail_route_404(self, client):
        resp = client.get("/api/media/999999")
        assert resp.status_code == 404

    def test_item_detail_includes_sources(self, client, db):
        """Phase 11-D：收藏作品详情返回 MediaSource 来源列表（免 N+1）。"""
        item = _mk_item(db, source="anilist", external_id="9253", title="Steins;Gate",
                        work_type="anime", release_date="2011-04-05")
        media_svc.ensure_media_for_item(item, db)
        db.commit()
        resp = client.get(f"/api/items/{item.id}/detail")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sources"] and data["sources"][0]["source"] == "anilist"
        assert data["sources"][0]["external_id"] == "9253"
        # 旧字段仍兼容
        assert data["id"] == item.id
        assert data["title"] == "Steins;Gate"


class TestMediaEntryNewFields:
    """Phase 12-C：MediaEntry 高价值结构化字段（duration/season/studios/themes/demographics/external_links）。"""

    def test_new_fields_saved_and_read(self, db):
        raw = {"source": "jikan", "detail": {"metadata": {
            "duration": "24 min per ep", "season": "Spring", "studios": ["White Fox"],
            "themes": ["Time Travel"], "demographics": ["Seinen"],
            "external_links": [{"label": "ANN", "url": "https://x"}]}}}
        item = _mk_item(db, source="jikan", external_id="1", title="作品", raw_metadata=raw)
        entry = media_svc.ensure_media_for_item(item, db)
        db.commit()
        e = db.get(MediaEntry, entry.id)
        assert e.duration == "24 min per ep"
        assert e.season == "Spring"
        assert json.loads(e.studios) == ["White Fox"]
        assert json.loads(e.themes) == ["Time Travel"]
        assert json.loads(e.demographics) == ["Seinen"]
        assert json.loads(e.external_links) == [{"label": "ANN", "url": "https://x"}]
        d = media_svc.media_detail(entry.id, db)
        assert d["duration"] == "24 min per ep"
        assert d["studios"] == ["White Fox"]
        assert d["external_links"] == [{"label": "ANN", "url": "https://x"}]

    def test_new_fields_empty_compat(self, db):
        item = _mk_item(db, raw_metadata={"source": "bangumi", "detail": {"metadata": {}}})
        entry = media_svc.ensure_media_for_item(item, db)
        db.commit()
        d = media_svc.media_detail(entry.id, db)
        assert d["duration"] is None
        assert d["studios"] == []
        assert d["themes"] == []
        assert d["external_links"] == []

    def test_migration_adds_media_entry_columns(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path}/old.db")
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE media_entries (id INTEGER PRIMARY KEY, canonical_title VARCHAR(255), genres TEXT)"
            ))
        Base.metadata.create_all(bind=engine)
        ensure_schema(bind=engine)
        cols = {c["name"] for c in inspect(engine).get_columns("media_entries")}
        for c in ("duration", "season", "studios", "themes", "demographics", "external_links"):
            assert c in cols
        engine.dispose()
