"""声优关系聚合接口测试（ADR 0032）：声优 → 角色 → 作品 三层关系、缺失声优处理"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app import ingest
from app.database import get_db


def _mk_client(db):
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def _add_item(db, title, chars):
    ingest.ingest_external(
        source="fake", external_id=title, title=title, content="",
        raw_metadata={"detail": {"metadata": {"characters": chars}}},
        db=db,
    )


class TestVoiceRelations:
    def test_empty(self, db):
        body = _mk_client(db).get("/api/voice-relations").json()
        assert body["actors"] == []
        assert body["works"] == []
        assert body["stats"]["actor_count"] == 0

    def test_aggregates_actor_to_works_and_roles(self, db):
        _add_item(db, "作品A", [
            {"id": 1, "name": "角色A1", "relation": "主角", "summary": "", "actors": ["声优甲", "声优乙"]},
            {"id": 2, "name": "角色A2", "relation": "配角", "summary": "", "actors": []},
        ])
        _add_item(db, "作品B", [
            {"id": 3, "name": "角色B1", "relation": "主角", "summary": "", "actors": ["声优甲"]},
        ])
        body = _mk_client(db).get("/api/voice-relations").json()
        assert body["stats"]["missing_actor_chars"] == 1  # 角色A2 无 actors
        assert body["stats"]["work_count"] == 2
        actors = {a["name"]: a for a in body["actors"]}
        assert body["stats"]["actor_count"] == 2
        jia = actors["声优甲"]
        assert jia["work_count"] == 2  # 跨两部作品（核心价值）
        assert jia["role_count"] == 2
        assert sorted(w["title"] for w in jia["works"]) == ["作品A", "作品B"]
        roles_of_A = next(w["roles"] for w in jia["works"] if w["title"] == "作品A")
        assert roles_of_A == ["角色A1"]
        yi = actors["声优乙"]
        assert yi["work_count"] == 1

    def test_roles_dedup_same_character(self, db):
        # 同一角色（同名）跨条目重复出现 → roles 去重为一条
        _add_item(db, "作品C", [
            {"id": 1, "name": "同名角色", "relation": "主角", "summary": "", "actors": ["声优甲"]},
            {"id": 2, "name": "同名角色", "relation": "配角", "summary": "", "actors": ["声优甲"]},
        ])
        body = _mk_client(db).get("/api/voice-relations").json()
        assert len(body["actors"]) == 1
        jia = body["actors"][0]
        assert jia["work_count"] == 1
        assert jia["works"][0]["roles"] == ["同名角色"]
        assert jia["role_count"] == 1

    def test_blank_actor_names_skipped(self, db):
        _add_item(db, "作品D", [
            {"id": 1, "name": "角色X", "relation": "主角", "summary": "", "actors": ["", "   ", "声优丙"]},
        ])
        body = _mk_client(db).get("/api/voice-relations").json()
        assert [a["name"] for a in body["actors"]] == ["声优丙"]

    def test_characters_without_actors_not_in_actor_map(self, db):
        _add_item(db, "作品E", [
            {"id": 1, "name": "无配音角色", "relation": "主角", "summary": "", "actors": []},
        ])
        body = _mk_client(db).get("/api/voice-relations").json()
        assert body["actors"] == []
        assert body["stats"]["missing_actor_chars"] == 1
        assert body["stats"]["work_count"] == 1  # 作品仍在 works 里
