"""角色图鉴：收藏入库存 detail raw_metadata、角色墙聚合、详情端点"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.connectors import registry
from app.connectors.base import ConnectorError, ConnectorManifest, ItemDetail
from app.database import get_db
from app import ingest
from app.models import Chunk, Item


CHAR_HUIYE = {"id": 66899, "name": "四宫辉夜", "image_url": "https://img/huiye.jpg",
              "relation": "主角", "summary": "学生会副会长。", "actors": ["古贺葵"]}
CHAR_SHIRAGAMI = {"id": 66900, "name": "白银御行", "image_url": "https://img/shiragami.jpg",
                  "relation": "主角", "summary": "学生会长。", "actors": []}
CHAR_FUJIWARA = {"id": 67408, "name": "藤原千花", "image_url": "https://img/fuji.jpg",
                 "relation": "主角", "summary": "学生会书记。", "actors": []}


class FakeDetailConnector:
    """注册进 registry 的假 Connector：get_detail 返回固定详情（角色数据）。"""
    name = "fakebg"
    manifest = ConnectorManifest(name="fakebg", display_name="Fake", version="0.1.0",
                                 base_url="https://api.bgm.tv",
                                 capabilities=["search", "get_detail"])
    proxy_url = None
    get_detail_calls = 0

    def search(self, query, **filters):
        return []

    def get_detail(self, external_id):
        type(self).get_detail_calls += 1
        if external_id == "A":
            return ItemDetail(
                source="fakebg", title="辉夜大小姐A", external_id="A",
                description="详细简介A。", image_url="https://img/a.jpg",
                metadata={"rating": 8.9, "tags": ["恋爱"], "characters": [CHAR_HUIYE, CHAR_SHIRAGAMI]},
            )
        return ItemDetail(
            source="fakebg", title="辉夜大小姐B", external_id="B",
            description="详细简介B。", image_url="https://img/b.jpg",
            metadata={"rating": 9.0, "tags": ["搞笑"], "characters": [CHAR_HUIYE, CHAR_FUJIWARA]},
        )


class SearchOnlyConnector:
    name = "searchonly"
    manifest = ConnectorManifest(name="searchonly", display_name="Search", version="0.1.0",
                                 base_url="https://api.example.com", capabilities=["search"])
    proxy_url = None

    def search(self, query, **filters):
        return []


@pytest.fixture(scope="function")
def client(db, fake_collection, patch_embeddings):
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    FakeDetailConnector.get_detail_calls = 0
    registry.register(FakeDetailConnector())
    registry.register(SearchOnlyConnector())
    try:
        yield TestClient(app)
    finally:
        registry.unregister("fakebg")
        registry.unregister("searchonly")


def _save(client, external_id):
    return client.post("/api/items/save-external", json={
        "source": "fakebg", "external_id": external_id,
        "title": "搜索级标题", "description": "搜索级简介",
        "image_url": "https://img/search.jpg", "tags": ["搜索标签"],
    })


class TestSaveExternalDetail:
    def test_save_stores_detail_raw_metadata(self, client):
        r = _save(client, "A")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["title"] == "辉夜大小姐A"  # detail 标题覆盖搜索级
        assert data["tags"] == ["恋爱"]  # detail 标签覆盖搜索标签

        # 从库里读回 raw_metadata
        item = client.get(f"/api/items/{data['item_id']}/detail").json()
        assert item["rating"] == 8.9
        assert [c["name"] for c in item["characters"]] == ["四宫辉夜", "白银御行"]
        raw = item["raw_metadata"]
        assert raw["detail"]["metadata"]["characters"][0]["actors"] == ["古贺葵"]

    def test_save_detail_failure_degrades(self, client, monkeypatch):
        def boom(self, external_id):
            raise ConnectorError("详情拉取失败")

        monkeypatch.setattr(FakeDetailConnector, "get_detail", boom)
        r = _save(client, "A")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["title"] == "搜索级标题"  # 降级到搜索级
        item = client.get(f"/api/items/{data['item_id']}/detail").json()
        assert item["characters"] == []
        assert item["raw_metadata"] is None

    def test_save_idempotent_backfills_legacy_item(self, client, db, fake_collection, patch_embeddings):
        # 旧条目（无 raw_metadata）：重新收藏后回填详情
        legacy = ingest.ingest_external(
            source="fakebg", external_id="LEGACY", title="旧条目",
            content="旧简介", db=db,
        )
        assert legacy.raw_metadata is None
        r = client.post("/api/items/save-external", json={
            "source": "fakebg", "external_id": "LEGACY", "title": "搜索级标题",
        })
        assert r.status_code == 200
        db.expire_all()  # 共享 session 的 identity map 可能缓存旧对象
        item = client.get(f"/api/items/{legacy.id}/detail").json()
        assert item["raw_metadata"] is not None
        assert len(item["characters"]) == 2


class TestCharactersWall:
    def test_aggregates_characters_across_works(self, client):
        _save(client, "A")
        _save(client, "B")
        r = client.get("/api/characters")
        assert r.status_code == 200
        chars = r.json()["characters"]
        by_name = {c["name"]: c for c in chars}
        # 四宫辉夜跨两部作品 → 合并
        assert by_name["四宫辉夜"]["works"] == [
            {"item_id": w["item_id"], "title": w["title"], "image_url": w["image_url"], "source": w["source"]}
            for w in by_name["四宫辉夜"]["works"]
        ]
        assert len(by_name["四宫辉夜"]["works"]) == 2
        assert by_name["四宫辉夜"]["actors"] == ["古贺葵"]
        assert len(by_name["白银御行"]["works"]) == 1
        assert len(by_name["藤原千花"]["works"]) == 1
        assert by_name["四宫辉夜"]["relation"] == "主角"

    def test_empty_when_no_saved_external(self, client):
        r = client.get("/api/characters")
        assert r.json()["characters"] == []


class TestDetailEndpoints:
    def test_external_detail_live(self, client):
        before = FakeDetailConnector.get_detail_calls
        r = client.get("/api/external/detail", params={"source": "fakebg", "external_id": "B"})
        assert r.status_code == 200
        body = r.json()
        assert body["title"] == "辉夜大小姐B"
        assert body["rating"] == 9.0
        assert len(body["characters"]) == 2
        assert FakeDetailConnector.get_detail_calls == before + 1

    def test_external_detail_unsupported_source(self, client):
        r = client.get("/api/external/detail", params={"source": "searchonly", "external_id": "1"})
        assert r.status_code == 404

    def test_external_detail_unknown_source(self, client):
        r = client.get("/api/external/detail", params={"source": "nope", "external_id": "1"})
        assert r.status_code == 404

    def test_item_detail_404(self, client):
        r = client.get("/api/items/99999/detail")
        assert r.status_code == 404


class TestSaveExternalReferenceChunks:
    """ADR 0025：收藏入库时下载完整资料（简介+角色小传）切分为 external_reference chunk。"""

    def test_save_builds_reference_chunks(self, client, db):
        _save(client, "A")
        item = db.query(Item).filter(Item.external_id == "A").first()
        assert item is not None
        chunks = db.query(Chunk).filter(Chunk.item_id == item.id).all()
        assert chunks, "收藏时应生成完整资料 chunk"
        assert all(c.source_type == "external_reference" for c in chunks)
        assert all(c.connector == "fakebg" for c in chunks)
        # 角色小传已进入参考文本
        assert any("四宫辉夜" in c.content for c in chunks)
        # raw_metadata 存了 reference_text（供后续重下判重）
        raw = item.raw_metadata
        assert raw["detail"]["metadata"]["reference_text"]

    def test_resave_keeps_chunks_unchanged(self, client, db):
        _save(client, "A")
        item = db.query(Item).filter(Item.external_id == "A").first()
        before = {c.embedding_ref for c in db.query(Chunk).filter(Chunk.item_id == item.id).all()}
        n_chunks = db.query(Chunk).count()
        _save(client, "A")  # 幂等重收藏（详情未变）
        after = {c.embedding_ref for c in db.query(Chunk).filter(Chunk.item_id == item.id).all()}
        assert after == before  # 未重建、未重复写向量
        assert db.query(Chunk).count() == n_chunks


class TestRefreshExternal:
    def test_refresh_rebuilds_missing_reference_chunks(self, client, db, fake_collection):
        _save(client, "A")
        item = db.query(Item).filter(Item.external_id == "A").first()
        db.query(Chunk).filter(Chunk.item_id == item.id).delete(synchronize_session=False)
        db.commit()
        r = client.post(f"/api/items/{item.id}/refresh-external")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["characters"], "刷新后角色数据应回来"
        chunks = db.query(Chunk).filter(Chunk.item_id == item.id).all()
        assert chunks
        assert all(c.source_type == "external_reference" for c in chunks)
        assert all(c.connector == "fakebg" for c in chunks)

    def test_refresh_uses_connector_limit(self, client, db):
        _save(client, "B")
        item = db.query(Item).filter(Item.external_id == "B").first()
        before = FakeDetailConnector.get_detail_calls
        client.post(f"/api/items/{item.id}/refresh-external")
        assert FakeDetailConnector.get_detail_calls == before + 1  # 走 get_detail（内部令牌桶限流）

    def test_refresh_rejects_local(self, client, db):
        from app import ingest
        it = ingest.ingest_text_document("本地笔记", "内容" * 20, db=db)
        r = client.post(f"/api/items/{it.id}/refresh-external")
        assert r.status_code == 400

    def test_refresh_404(self, client):
        assert client.post("/api/items/99999/refresh-external").status_code == 404


class TestItemDetailSocial:
    """ADR 0026：detail 暴露 reference_text + social（热度/评分分布替代数据）。"""

    def test_detail_exposes_reference_text_and_social(self, client, db):
        _save(client, "A")
        item = db.query(Item).filter(Item.external_id == "A").first()
        detail = client.get(f"/api/items/{item.id}/detail").json()
        assert detail["reference_text"]  # 完整资料文本已暴露
        assert "reference_text" in (detail["raw_metadata"]["detail"]["metadata"])
        assert "social" in detail

    def test_detail_social_bangumi(self, client, db):
        from app import ingest as _ingest
        item = _ingest.ingest_external(
            source="fakebg", external_id="S1", title="X", content="x",
            raw_metadata={"source": "fakebg", "detail": {"metadata": {
                "rating_info": {"rank": 5, "total": 100, "count": {"10": 50}, "score": 8.5},
                "collection": {"wish": 1, "collect": 2, "doing": 3, "on_hold": 0, "dropped": 0},
            }}},
            db=db,
        )
        d = client.get(f"/api/items/{item.id}/detail").json()
        assert d["social"]["rating_rank"] == 5
        assert d["social"]["rating_total"] == 100
        assert d["social"]["collection"]["collect"] == 2


class TestRelatedSources:
    """ADR 0026 多来源切换：同作品跨来源各自收藏，按规范化标题匹配兄弟条目。"""

    def test_related_by_normalized_title(self, client, db):
        from app import ingest as _ingest
        a = _ingest.ingest_external(source="fakebg", external_id="R1", title="命运石之门",
                                    content="", db=db)
        b = _ingest.ingest_external(source="moegirl", external_id="R2", title="命运石之门",
                                    content="", db=db)
        c = _ingest.ingest_external(source="vndb", external_id="R3", title="STEINS;GATE",
                                    content="", db=db)
        assert [s["source"] for s in client.get(f"/api/items/{a.id}/related").json()] == ["moegirl"]
        assert [s["source"] for s in client.get(f"/api/items/{b.id}/related").json()] == ["fakebg"]
        assert client.get(f"/api/items/{c.id}/related").json() == []  # 英文名不匹配中文名

    def test_related_punctuation_normalized(self, client, db):
        from app import ingest as _ingest
        a = _ingest.ingest_external(source="fakebg", external_id="N1", title="空之境界·终章",
                                    content="", db=db)
        b = _ingest.ingest_external(source="moegirl", external_id="N2", title="空之境界 终章",
                                    content="", db=db)
        assert [s["source"] for s in client.get(f"/api/items/{a.id}/related").json()] == ["moegirl"]

    def test_local_item_no_related(self, client, db):
        from app import ingest as _ingest
        it = _ingest.ingest_text_document("本地笔记", "内容", db=db)
        assert client.get(f"/api/items/{it.id}/related").json() == []

    def test_related_404(self, client):
        assert client.get("/api/items/99999/related").status_code == 404
