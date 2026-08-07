"""API 路由集成测试（内存数据库 + 假向量库 + 假 embedding / LLM）"""
import io
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.database import get_db


@pytest.fixture(scope="function")
def client(db, fake_collection, patch_embeddings):
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _upload_md(client, content="# 标题\n\n这是一段测试内容。", title="测试文档", tags="RAG,测试"):
    return client.post(
        "/api/items/upload",
        files={"file": ("note.md", io.BytesIO(content.encode("utf-8")), "text/markdown")},
        data={"title": title, "tags": tags},
    )


class TestItemRoutes:
    def test_upload_text_creates_note(self, client):
        resp = _upload_md(client)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["type"] == "note"
        assert data["chunks_count"] >= 1
        assert data["tags"] == ["RAG", "测试"]
        assert data["item_id"] > 0

    def test_upload_txt_md(self, client):
        # .txt.md（双扩展名文本文件，常见于部分笔记导出）应作为 markdown/note 导入，
        # 且标题剥掉 .txt.md 整段扩展名
        resp = client.post(
            "/api/items/upload",
            files={"file": ("notes.txt.md", io.BytesIO("# 标题\n\n正文内容。".encode("utf-8")), "text/markdown")},
            data={"title": ""},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["type"] == "note"
        assert data["chunks_count"] >= 1
        assert data["title"] == "notes"

    def test_upload_unsupported_type(self, client):
        resp = client.post(
            "/api/items/upload",
            files={"file": ("a.xyz", io.BytesIO(b"data"), "application/octet-stream")},
            data={"title": "x"},
        )
        assert resp.status_code == 400

    def test_upload_image(self, client, tmp_path):
        resp = client.post(
            "/api/items/upload",
            files={"file": ("pic.png", io.BytesIO(b"\x89PNG\r\n\x1a\nfakedata"), "image/png")},
            data={"title": "图片"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "image"
        assert data["chunks_count"] == 0

    def test_create_item_json_invalid_type(self, client):
        resp = client.post("/api/items", json={"title": "x", "type": "video"})
        assert resp.status_code == 400

    def test_upload_duplicate_returns_duplicated_flag(self, client):
        md = "# 标题\n\n这是一段重复测试内容。"
        first = _upload_md(client, content=md)
        assert first.json()["duplicated"] is False
        second = _upload_md(client, content=md)
        assert second.status_code == 200
        assert second.json()["duplicated"] is True
        assert second.json()["item_id"] == first.json()["item_id"]
        # 强制导入（multipart 的 force 字段）
        forced = client.post(
            "/api/items/upload",
            files={"file": ("dup.md", io.BytesIO(md.encode("utf-8")), "text/markdown")},
            data={"title": "强制", "tags": "", "force": "true"},
        )
        assert forced.json()["duplicated"] is False
        assert forced.json()["item_id"] != first.json()["item_id"]

    def test_upload_image_duplicate_no_extra_file(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.settings.upload_dir", str(tmp_path))
        png = b"\x89PNG\r\n\x1a\nfakedata"
        files1 = {"file": ("p1.png", io.BytesIO(png), "image/png")}
        files2 = {"file": ("p2.png", io.BytesIO(png), "image/png")}
        r1 = client.post("/api/items/upload", files=files1, data={"title": "图1"})
        assert r1.json()["duplicated"] is False
        r2 = client.post("/api/items/upload", files=files2, data={"title": "图2"})
        assert r2.json()["duplicated"] is True
        assert r2.json()["item_id"] == r1.json()["item_id"]
        assert len(list(tmp_path.iterdir())) == 1, "重复图片不应再写文件"

    def test_create_item_json_force(self, client):
        body = {"title": "JSON文档", "type": "note", "content": "JSON 内容" * 10}
        r1 = client.post("/api/items", json=body)
        assert r1.json()["duplicated"] is False
        r2 = client.post("/api/items", json=body)
        assert r2.json()["duplicated"] is True
        r3 = client.post("/api/items", json={**body, "title": "强制", "force": True})
        assert r3.json()["duplicated"] is False

    def test_list_get_delete_item(self, client):
        item_id = _upload_md(client).json()["item_id"]
        listed = client.get("/api/items").json()["items"]
        assert any(i["id"] == item_id for i in listed)
        got = client.get(f"/api/items/{item_id}")
        assert got.status_code == 200
        assert got.json()["title"] == "测试文档"
        assert client.get("/api/items/{item_id}/status".format(item_id=item_id)).json()["chunks_count"] >= 1
        assert client.get("/api/items/99999").status_code == 404
        assert client.delete(f"/api/items/{item_id}").status_code == 200
        assert client.get(f"/api/items/{item_id}").status_code == 404

    def test_tags_endpoint(self, client):
        _upload_md(client, tags="RAG,测试")
        resp = client.get("/api/tags")
        names = {t["name"] for t in resp.json()}
        assert {"RAG", "测试"} <= names


class TestItemFiltering:
    def _seed(self, client):
        _upload_md(client, content="# 文档A\n\n带 RAG 标签的内容，关于向量检索。", title="文档A", tags="RAG,原理")
        _upload_md(client, content="# 文档B\n\n带 RAG 标签但无原理标签。", title="文档B", tags="RAG")
        _upload_md(client, content="# 文档C\n\n无标签的普通笔记。", title="文档C", tags="")
        resp = client.post(
            "/api/items/upload",
            files={"file": ("pic.png", io.BytesIO(b"\x89PNG\r\n\x1a\nfakedata"), "image/png")},
            data={"title": "图片", "tags": "原理"},
        )
        assert resp.status_code == 200

    def test_filter_by_type(self, client):
        self._seed(client)
        data = client.get("/api/items", params={"type": "image"}).json()
        assert data["total"] == 1
        assert all(i["type"] == "image" for i in data["items"])

    def test_filter_by_tag_any(self, client):
        self._seed(client)
        data = client.get("/api/items", params={"tag": ["RAG"]}).json()
        assert data["total"] == 2
        assert {i["title"] for i in data["items"]} == {"文档A", "文档B"}

    def test_filter_by_tag_all(self, client):
        self._seed(client)
        data = client.get("/api/items", params={"tag": ["RAG", "原理"], "tag_match": "all"}).json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "文档A"

    def test_total_counts_filtered_not_paginated(self, client):
        self._seed(client)
        data = client.get("/api/items", params={"tag": ["RAG"], "limit": 1}).json()
        assert data["total"] == 2
        assert len(data["items"]) == 1


class TestTagManagement:
    def test_rename_tag(self, client):
        _upload_md(client, tags="旧名")
        tag_id = next(t["id"] for t in client.get("/api/tags").json() if t["name"] == "旧名")
        resp = client.patch(f"/api/tags/{tag_id}", json={"name": "新名"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "新名"
        names = {t["name"] for t in client.get("/api/tags").json()}
        assert "新名" in names and "旧名" not in names

    def test_rename_conflict_409(self, client):
        _upload_md(client, tags="标签A,标签B")
        tags = client.get("/api/tags").json()
        tag_a = next(t["id"] for t in tags if t["name"] == "标签A")
        resp = client.patch(f"/api/tags/{tag_a}", json={"name": "标签B"})
        assert resp.status_code == 409

    def test_delete_tag_keeps_item(self, client):
        _upload_md(client, content="# 文档\n\n要删除标签的内容。", tags="临时标签")
        item_id = client.get("/api/items").json()["items"][0]["id"]
        tag_id = next(t["id"] for t in client.get("/api/tags").json() if t["name"] == "临时标签")
        assert client.delete(f"/api/tags/{tag_id}").status_code == 200
        assert client.get(f"/api/items/{item_id}").json()["tags"] == []
        assert client.get("/api/tags").json() == []

    def test_merge_tags(self, client):
        _upload_md(client, content="# 文档A\n\n合并测试内容。", title="文档A", tags="合并源,目标")
        _upload_md(client, content="# 文档B\n\n另一篇内容。", title="文档B", tags="合并源")
        tags = client.get("/api/tags").json()
        src_id = next(t["id"] for t in tags if t["name"] == "合并源")
        tgt_id = next(t["id"] for t in tags if t["name"] == "目标")
        resp = client.post("/api/tags/merge", json={"target_tag_id": tgt_id, "source_tag_ids": [src_id]})
        assert resp.status_code == 200
        assert resp.json()["name"] == "目标"
        assert resp.json()["count"] == 2
        names = {t["name"] for t in client.get("/api/tags").json()}
        assert "合并源" not in names
        # 两个文档都带有"目标"标签
        for item in client.get("/api/items").json()["items"]:
            assert "目标" in item["tags"]

    def test_delete_missing_tag_404(self, client):
        assert client.delete("/api/tags/99999").status_code == 404


class TestSearchRoutes:
    def test_search_returns_results(self, client):
        _upload_md(client, content="# 文档\n\n向量检索与余弦相似度的介绍。")
        resp = client.post("/api/search", json={"query": "向量检索", "top_k": 5})
        assert resp.status_code == 200
        assert isinstance(resp.json()["results"], list)

    def test_search_with_tag_filter(self, client):
        _upload_md(client, content="匹配内容", tags="A")
        resp = client.post("/api/search", json={"query": "匹配内容", "tag_filter": ["不存在的标签"]})
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    def test_upload_cover(self, client):
        item_id = _upload_md(client).json()["item_id"]
        resp = client.post(
            f"/api/items/{item_id}/cover",
            files={"file": ("cover.png", io.BytesIO(b"\x89PNG\r\n\x1a\nfakedata"), "image/png")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["image_url"].startswith("/static/thumbnails/cover_")
        assert "file_path" in data

    def test_upload_cover_bad_type(self, client):
        item_id = _upload_md(client).json()["item_id"]
        resp = client.post(
            f"/api/items/{item_id}/cover",
            files={"file": ("a.txt", io.BytesIO(b"x"), "text/plain")},
        )
        assert resp.status_code == 400

    def test_upload_cover_missing_item(self, client):
        resp = client.post(
            "/api/items/99999/cover",
            files={"file": ("c.png", io.BytesIO(b"x"), "image/png")},
        )
        assert resp.status_code == 404


class TestRagRoutes:
    def test_non_stream_answer(self, client, monkeypatch):
        _upload_md(client, content="# 文档\n\n这是回答问题的依据内容。")
        async def fake_non_stream(query, chunks):
            return "生成的答案"
        monkeypatch.setattr("app.rag.generate_answer_non_stream", fake_non_stream)
        resp = client.post("/api/rag/query", json={"query": "问题"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"] == "生成的答案"
        assert data["retrieved_chunks"]

    def test_stream_sse_events(self, client, monkeypatch):
        _upload_md(client, content="# 文档\n\n流式回答依据内容。")
        async def fake_generate(query, chunks, stream=True):
            yield "答案"
            yield "片段"
        monkeypatch.setattr("app.rag.generate_answer", fake_generate)

        events = []
        with client.stream("POST", "/api/rag/query/stream", json={"query": "问题"}) as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

        types = [e["type"] for e in events]
        assert types[0] == "sources"
        assert "chunk" in types
        assert types[-1] == "done"
        assert "".join(e.get("content", "") for e in events if e["type"] == "chunk") == "答案片段"

    def test_stream_llm_error_event(self, client, monkeypatch):
        _upload_md(client, content="# 文档\n\n错误测试内容。")
        from app.rag import LLMError

        async def fake_generate(query, chunks, stream=True):
            raise LLMError("DeepSeek API 鉴权失败")
            yield  # pragma: no cover - 使其成为 async generator

        monkeypatch.setattr("app.rag.generate_answer", fake_generate)

        events = []
        with client.stream("POST", "/api/rag/query/stream", json={"query": "问题"}) as resp:
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        assert events[-1]["type"] == "error"
        assert "鉴权" in events[-1]["message"]


class TestConnectorRoutes:
    def test_save_external(self, client):
        resp = client.post(
            "/api/items/save-external",
            json={
                "source": "bangumi",
                "external_id": "301",
                "title": "辉夜大小姐想让我告白",
                "description": "学生会长与副会长互相算计的恋爱喜剧。",
                "image_url": "https://lain.bgm.tv/pic/cover/l.jpg",
                "tags": ["恋爱", "搞笑"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "external_ref"
        assert data["item_id"] > 0
        assert data["tags"] == ["恋爱", "搞笑"]

    def test_save_external_idempotent(self, client):
        body = {
            "source": "bangumi", "external_id": "302", "title": "某动画",
            "description": "简介文字。",
        }
        r1 = client.post("/api/items/save-external", json=body)
        r2 = client.post("/api/items/save-external", json=body)
        assert r1.json()["item_id"] == r2.json()["item_id"]
        assert client.get("/api/items").json()["total"] == 1

    def test_save_external_rejects_local_source(self, client):
        resp = client.post(
            "/api/items/save-external",
            json={"source": "local", "external_id": "x", "title": "x"},
        )
        assert resp.status_code == 400

    def test_federated_search_returns_grouped(self, client, monkeypatch):
        _upload_md(client, content="# 本地文档\n\n本地知识库内容。")
        from app.connectors.base import SearchResult

        class FakeConnector:
            name = "fake"
            manifest = None

            def search(self, query, **filters):
                return [
                    SearchResult(
                        source="fake", title="外部结果",
                        external_id="ext1", description="外部描述",
                        rating=9.0, tags=["虚构"],
                    )
                ]

        monkeypatch.setattr(
            "app.api.routes.connector_registry.get_enabled_connectors",
            lambda: [FakeConnector()],
        )
        resp = client.post(
            "/api/search/federated", json={"query": "测试", "top_k": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "测试"
        assert data["results"][0]["source"] == "fake"
        assert data["results"][0]["title"] == "外部结果"

    def test_federated_search_connector_error_degrades(self, client, monkeypatch):
        """单个 Connector 失败应降级（200 + errors），而非整体 502。"""
        from app.connectors.base import ConnectorError

        class FailConnector:
            name = "fail"
            manifest = None

            def search(self, query, **filters):
                raise ConnectorError("外部 API 挂了")

        monkeypatch.setattr(
            "app.api.routes.connector_registry.get_enabled_connectors",
            lambda: [FailConnector()],
        )
        resp = client.post(
            "/api/search/federated", json={"query": "测试"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert "fail" in data["errors"]
        assert "外部 API 挂了" in data["errors"]["fail"]

    def test_list_connectors(self, client, monkeypatch):
        from app.connectors.base import ConnectorManifest

        class FakeConnector:
            name = "bangumi"
            manifest = ConnectorManifest(name="bangumi", display_name="Bangumi", version="0.1.0")

        monkeypatch.setattr(
            "app.api.routes.connector_registry.list_manifests",
            lambda: [FakeConnector.manifest],
        )
        monkeypatch.setattr(
            "app.api.routes.connector_registry.is_enabled",
            lambda n: True,
        )
        resp = client.get("/api/connectors")
        assert resp.status_code == 200
        assert resp.json()[0]["name"] == "bangumi"
        assert resp.json()[0]["enabled"] is True


class TestDeclarativeConnectorRoutes:
    CONFIG = {
        "name": "my-api",
        "display_name": "我的API",
        "base_url": "https://api.example.com",
        "search_endpoint": "/search?q={query}",
        "result_path": "items",
        "field_map": {"title": "title", "external_id": "id"},
    }

    def test_create_declarative_connector(self, client, monkeypatch):
        from app.connectors import persistence as cp
        monkeypatch.setattr(cp, "save_declarative_config", lambda c, enabled=True: None)
        resp = client.post("/api/connectors", json=self.CONFIG)
        assert resp.status_code == 200
        assert resp.json()["name"] == "my-api"
        assert resp.json()["enabled"] is True
        try:
            assert registry_get("my-api") is not None
        finally:
            registry_unreg("my-api")

    def test_create_invalid_connector(self, client):
        resp = client.post(
            "/api/connectors",
            json={**self.CONFIG, "field_map": {"title": "t"}},  # 缺 external_id
        )
        assert resp.status_code == 400

    def test_delete_declarative_connector(self, client, monkeypatch):
        from app.connectors import persistence as cp
        monkeypatch.setattr(cp, "delete_declarative_config", lambda n: True)
        registry_register_myapi()
        try:
            resp = client.delete("/api/connectors/my-api")
            assert resp.status_code == 200
            assert registry_get("my-api") is None
        finally:
            registry_unreg("my-api")

    def test_federated_search_uses_declarative(self, client, monkeypatch):
        from app.connectors.base import DeclarativeConnector
        registry_register_myapi()
        try:
            conn = registry_get("my-api")
            monkeypatch.setattr(
                conn, "search",
                lambda query, **f: [type("R", (), {"source": "my-api", "title": "声明式结果",
                    "subtitle": None, "description": "desc", "image_url": None,
                    "external_id": "e1", "rating": None, "tags": [], "raw": None})()],
            )
            monkeypatch.setattr(
                "app.api.routes.connector_registry.get_enabled_connectors",
                lambda: [conn],
            )
            resp = client.post("/api/search/federated", json={"query": "测试"})
            assert resp.status_code == 200
            assert resp.json()["results"][0]["title"] == "声明式结果"
        finally:
            registry_unreg("my-api")


def registry_get(name):
    from app.connectors import registry as r
    return r.get_connector(name)


def registry_unreg(name):
    from app.connectors import registry as r
    r.unregister(name)


def registry_register_myapi():
    from app.connectors import registry as r
    from app.connectors.base import DeclarativeConnector
    config = dict(TestDeclarativeConnectorRoutes.CONFIG)
    r.register(DeclarativeConnector(config), enabled=True)


class TestReviewRoutes:
    def test_create_and_list(self, client):
        item_id = _upload_md(client).json()["item_id"]
        resp = client.post(f"/api/items/{item_id}/reviews", json={
            "content": "这是一段很长的读后感内容。" * 30,
            "title": "看完感想",
            "rating": 8,
            "status": "看完",
            "spoiler": True,
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["rating"] == 8
        assert data["status"] == "看完"
        assert data["spoiler"] is True
        assert data["item_title"] == "测试文档"

        listing = client.get(f"/api/items/{item_id}/reviews").json()
        assert len(listing) == 1
        assert listing[0]["id"] == data["id"]

    def test_review_font_size_persists(self, client):
        item_id = _upload_md(client).json()["item_id"]
        rid = client.post(f"/api/items/{item_id}/reviews", json={
            "content": "书评内容", "font_size": 18,
        }).json()["id"]
        assert client.get(f"/api/items/{item_id}/reviews").json()[0]["font_size"] == 18
        client.patch(f"/api/reviews/{rid}", json={"font_size": 20})
        assert client.get(f"/api/items/{item_id}/reviews").json()[0]["font_size"] == 20

    def test_create_invalid_status(self, client):
        item_id = _upload_md(client).json()["item_id"]
        resp = client.post(f"/api/items/{item_id}/reviews", json={
            "content": "内容", "status": "未知",
        })
        assert resp.status_code == 400

    def test_create_missing_item(self, client):
        resp = client.post("/api/items/99999/reviews", json={"content": "内容"})
        assert resp.status_code == 400

    def test_update_review(self, client):
        item_id = _upload_md(client).json()["item_id"]
        rid = client.post(f"/api/items/{item_id}/reviews", json={"content": "旧内容" * 20}).json()["id"]
        resp = client.patch(f"/api/reviews/{rid}", json={"content": "新内容完全不同" * 30, "rating": 9, "spoiler": True})
        assert resp.status_code == 200
        assert resp.json()["content"] != "旧内容" * 20
        assert resp.json()["rating"] == 9
        assert resp.json()["spoiler"] is True

    def test_delete_review(self, client):
        item_id = _upload_md(client).json()["item_id"]
        rid = client.post(f"/api/items/{item_id}/reviews", json={"content": "内容" * 20}).json()["id"]
        assert client.delete(f"/api/reviews/{rid}").status_code == 200
        assert client.get(f"/api/items/{item_id}/reviews").json() == []
        assert client.delete(f"/api/reviews/{rid}").status_code == 404

    def test_review_visible_in_search(self, client):
        item_id = _upload_md(client).json()["item_id"]
        client.post(f"/api/items/{item_id}/reviews", json={
            "content": "关于量子纠缠结局的深度伏笔分析" * 20, "title": "结局分析",
        })
        resp = client.post("/api/search", json={"query": "量子纠缠伏笔", "top_k": 5})
        assert resp.status_code == 200
        review_hits = [r for r in resp.json()["results"] if r.get("source_type") == "review"]
        assert review_hits
        assert review_hits[0]["review_id"] is not None

    def test_global_reviews_list(self, client):
        i1 = _upload_md(client, title="文档A").json()["item_id"]
        i2 = _upload_md(client, title="文档B").json()["item_id"]
        client.post(f"/api/items/{i1}/reviews", json={"content": "内容一" * 10})
        client.post(f"/api/items/{i2}/reviews", json={"content": "内容二" * 10})
        allr = client.get("/api/reviews").json()
        assert len(allr) == 2

    def test_public_rating_for_external_item(self, client):
        resp = client.post("/api/items/save-external", json={
            "source": "bangumi", "external_id": "301", "title": "辉夜",
            "description": "简介", "image_url": "https://x/img.jpg",
        })
        item_id = resp.json()["item_id"]
        # raw_metadata 需要带 rating
        from app.database import SessionLocal
        from app.models import Item
        db = SessionLocal()
        it = db.get(Item, item_id)
        it.raw_metadata = {"rating": {"score": 8.9}}
        db.commit()
        db.close()

        rid = client.post(f"/api/items/{item_id}/reviews", json={"content": "我的评分" * 10, "rating": 7}).json()["id"]
        detail = client.patch(f"/api/reviews/{rid}", json={}).json()
        assert detail["public_rating"] == 8.9
        assert detail["rating"] == 7

    def test_item_detail_includes_my_rating_aggregate(self, client):
        resp = client.post("/api/items/save-external", json={
            "source": "bangumi", "external_id": "302", "title": "另一部",
            "description": "简介",
        })
        item_id = resp.json()["item_id"]
        client.post(f"/api/items/{item_id}/reviews", json={"content": "r1" * 10, "rating": 6})
        client.post(f"/api/items/{item_id}/reviews", json={"content": "r2" * 10, "rating": 8})
        client.post(f"/api/items/{item_id}/reviews", json={"content": "r3" * 10})  # 未打分
        d = client.get(f"/api/items/{item_id}/detail").json()
        assert d["my_rating"] == 7.0  # (6+8)/2，忽略未打分
        assert "file_path" in d  # 本地缓存封面字段（安利卡导出用）


class TestBatchOps:
    """批量打标签 / 批量删除 / 单条标签（交互打磨）"""

    def _mk(self, client, title, tags=None):
        return client.post("/api/items", json={
            "title": title, "type": "note", "content": f"{title} 的内容", "tag_names": tags or [],
        }).json()["item_id"]

    def test_batch_add_tags(self, client):
        i1 = self._mk(client, "甲")
        i2 = self._mk(client, "乙")
        r = client.post("/api/items/batch/tags", json={
            "item_ids": [i1, i2], "tag_names": ["批量", "收藏"], "mode": "add",
        })
        assert r.status_code == 200
        assert r.json()["updated"] == 2
        d1 = client.get(f"/api/items/{i1}").json()
        assert set(d1["tags"]) == {"批量", "收藏"}

    def test_batch_set_and_remove_tags(self, client):
        i1 = self._mk(client, "丙", tags=["旧A", "旧B"])
        client.post("/api/items/batch/tags", json={"item_ids": [i1], "tag_names": ["新"], "mode": "set"})
        d = client.get(f"/api/items/{i1}").json()
        assert d["tags"] == ["新"]
        client.post("/api/items/batch/tags", json={"item_ids": [i1], "tag_names": ["新"], "mode": "remove"})
        assert client.get(f"/api/items/{i1}").json()["tags"] == []

    def test_batch_delete(self, client):
        i1 = self._mk(client, "丁")
        i2 = self._mk(client, "戊")
        r = client.post("/api/items/batch/delete", json={"item_ids": [i1, i2]})
        assert r.json()["deleted"] == 2
        assert client.get(f"/api/items/{i1}").status_code == 404
        assert client.get(f"/api/items/{i2}").status_code == 404

    def test_batch_delete_empty_ok(self, client):
        assert client.post("/api/items/batch/delete", json={"item_ids": []}).json()["deleted"] == 0

    def test_single_item_tags(self, client):
        i1 = self._mk(client, "己")
        r = client.post(f"/api/items/{i1}/tags", json={"tag_names": ["单个"], "mode": "add"})
        assert r.status_code == 200
        assert "单个" in r.json()["tags"]
        # 不存在的条目
        assert client.post("/api/items/99999/tags", json={"tag_names": ["x"]}).status_code == 404
