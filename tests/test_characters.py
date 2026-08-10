"""Character 角色实体（P4 / ADR 0048）：提炼/去重/同步/回填 + 角色墙/声优图谱改走表"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import characters
from app.api.routes import router
from app.database import Base, get_db
from app.models import Character, Item

RAW_A = {
    "source": "bangumi",
    "detail": {"metadata": {"characters": [
        {"id": 1, "name": "岡崎朋也", "image_url": "a.jpg", "relation": "主角",
         "summary": "s", "actors": ["中村悠一"]},
        {"id": 2, "name": "古河渚", "image_url": "b.jpg", "relation": "主角",
         "summary": "s2", "actors": ["中原麻衣"]},
    ]}},
}
RAW_B = {
    "source": "bangumi",
    "detail": {"metadata": {"characters": [
        {"id": 2, "name": "古河渚", "image_url": "b2.jpg", "relation": "配角",
         "summary": "s2", "actors": ["中原麻衣"]},
    ]}},
}


def _ext_item(db, title, source="bangumi", raw=None):
    it = Item(title=title, type="external_ref", source=source, content="x", raw_metadata=raw)
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


class TestSync:
    def test_sync_creates_and_dedups(self, db):
        a = _ext_item(db, "A", raw=RAW_A)
        b = _ext_item(db, "B", raw=RAW_B)
        characters.sync_characters(a, db)
        characters.sync_characters(b, db)
        db.commit()
        assert db.query(Character).count() == 2  # 古河渚 跨作品去重
        gu = db.query(Character).filter(Character.name == "古河渚").one()
        assert gu.relation == "主角"  # 主角优先合并（B 里是配角）
        assert {w.id for w in gu.works} == {a.id, b.id}
        you = db.query(Character).filter(Character.name == "岡崎朋也").one()
        assert json.loads(you.actors) == ["中村悠一"]

    def test_resync_removes_stale_links_and_orphans(self, db):
        a = _ext_item(db, "A", raw=RAW_A)
        characters.sync_characters(a, db)
        db.commit()
        assert db.query(Character).count() == 2
        # 刷新后角色清空 → 重建应删除旧链接与孤儿角色
        a.raw_metadata = {"source": "bangumi", "detail": {"metadata": {"characters": []}}}
        db.commit()
        characters.sync_characters(a, db)
        db.commit()
        assert db.query(Character).count() == 0
        assert a.characters == []

    def test_backfill_all(self, db):
        _ext_item(db, "A", raw=RAW_A)
        _ext_item(db, "B", raw=RAW_B)
        _ext_item(db, "note", source="local")  # 本地不动
        n = characters.backfill_characters(db.bind)
        assert n == 2
        assert db.query(Character).count() == 2


class TestApi:
    @pytest.fixture
    def client(self, db):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        def override_get_db():
            yield db
        app.dependency_overrides[get_db] = override_get_db
        return TestClient(app)

    def test_characters_and_voice_from_table(self, client, db):
        a = _ext_item(db, "A", raw=RAW_A)
        b = _ext_item(db, "B", raw=RAW_B)
        characters.backfill_characters(db.bind)
        chars = client.get("/api/characters").json()["characters"]
        names = {c["name"]: c for c in chars}
        assert set(names) == {"岡崎朋也", "古河渚"}
        assert names["古河渚"]["relation"] == "主角"
        assert {w["item_id"] for w in names["古河渚"]["works"]} == {a.id, b.id}
        v = client.get("/api/voice-relations").json()
        actor_names = {x["name"]: x for x in v["actors"]}
        assert "中原麻衣" in actor_names
        works_of_actor = {w["item_id"] for w in actor_names["中原麻衣"]["works"]}
        assert works_of_actor == {a.id, b.id}  # 声优在古河渚（两作品）中都配过
        assert "古河渚" in actor_names["中原麻衣"]["works"][0]["roles"]
        assert v["stats"]["actor_count"] >= 1
