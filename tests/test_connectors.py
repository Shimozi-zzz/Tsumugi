"""Connector 层测试：registry / bangumi normalize（mock 响应）/ 收藏入库 / 声明式"""
import pytest

from app.connectors import registry
from app.connectors.bangumi.connector import BangumiConnector
from app.connectors.base import (
    ConnectorError, ConnectorManifest, DeclarativeConnector, SearchResult, ItemDetail,
)
from app import ingest
from app.models import Item


SAMPLE_SUBJECT = {
    "id": 301,
    "name": "かぐや様は告らせたい",
    "name_cn": "辉夜大小姐想让我告白",
    "summary": "学生会长与副会长互相算计让对方先表白的恋爱喜剧。",
    "images": {"large": "https://lain.bgm.tv/pic/cover/l.jpg"},
    "rating": {"score": 8.9},
    "tags": [{"name": "恋爱"}, {"name": "搞笑"}],
    "type": 2,
    "date": "2019-01-12",
    "eps": 12,
    "volumes": None,
}


class TestManifest:
    def test_from_dict(self):
        m = ConnectorManifest.from_dict(
            {"name": "bangumi", "display_name": "Bangumi", "version": "0.1.0",
             "base_url": "https://api.bgm.tv", "capabilities": ["search"]}
        )
        assert m.name == "bangumi"
        assert m.capabilities == ["search"]
        assert m.auth_type == "none"


class TestRegistry:
    def test_register_and_enable(self):
        connector = BangumiConnector()
        registry.register(connector, enabled=True)
        try:
            assert registry.get_connector("bangumi") is connector
            assert registry.is_enabled("bangumi")
            assert registry.list_manifests()[0].name == "bangumi"
            assert connector in registry.get_enabled_connectors()
            registry.set_enabled("bangumi", False)
            assert connector not in registry.get_enabled_connectors()
        finally:
            registry.unregister("bangumi")

    def test_discover_finds_bangumi(self):
        names = registry.discover()
        try:
            assert "bangumi" in names
            assert registry.get_connector("bangumi") is not None
        finally:
            registry.unregister("bangumi")


class TestBangumiNormalize:
    def test_subject_to_search_result(self):
        from app.connectors.bangumi.connector import _subject_to_search_result
        r = _subject_to_search_result(SAMPLE_SUBJECT)
        assert isinstance(r, SearchResult)
        assert r.source == "bangumi"
        assert r.title == "辉夜大小姐想让我告白"
        assert r.subtitle == "かぐや様は告らせたい"
        assert r.external_id == "301"
        assert r.rating == 8.9
        assert "恋爱" in r.tags
        assert r.raw is SAMPLE_SUBJECT

    def test_subject_to_detail(self):
        from app.connectors.bangumi.connector import _subject_to_detail
        d = _subject_to_detail(SAMPLE_SUBJECT)
        assert isinstance(d, ItemDetail)
        assert d.external_id == "301"
        assert d.metadata["eps"] == 12
        assert d.metadata["type"] == 2

    def test_normalize_to_item_fields(self):
        conn = BangumiConnector()
        fields = conn.normalize(SAMPLE_SUBJECT)
        assert fields["title"] == "辉夜大小姐想让我告白"
        assert fields["type"] == "external_ref"
        assert fields["source"] == "bangumi"
        assert fields["external_id"] == "301"
        assert fields["image_url"].startswith("https://")
        assert "恋爱" in fields["tags"]
        assert fields["raw_metadata"] is SAMPLE_SUBJECT


class TestSearch:
    def test_empty_query_returns_empty(self):
        conn = BangumiConnector()
        assert conn.search("  ") == []

    def test_search_uses_cache(self, monkeypatch):
        conn = BangumiConnector()
        calls = []

        def fake_request(method, path, **kwargs):
            calls.append(path)
            return {"data": [SAMPLE_SUBJECT]}

        monkeypatch.setattr(conn, "_request", fake_request)
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
        monkeypatch.setattr(conn._cache, "set", lambda k, v: None)

        first = conn.search("辉夜")
        assert len(first) == 1
        assert first[0].external_id == "301"


class TestSaveExternal:
    def test_save_external_idempotent(self, db, fake_collection, patch_embeddings):
        item1 = ingest.ingest_external(
            source="bangumi", external_id="301", title="辉夜大小姐想让我告白",
            content=SAMPLE_SUBJECT["summary"], tags=["恋爱"], db=db,
        )
        item2 = ingest.ingest_external(
            source="bangumi", external_id="301", title="辉夜大小姐想让我告白",
            content=SAMPLE_SUBJECT["summary"], db=db,
        )
        assert item2.id == item1.id
        assert db.query(Item).count() == 1
        assert item1.type == "external_ref"
        assert item1.external_id == "301"
        assert item1.source == "bangumi"
        assert [t.name for t in item1.tags] == ["恋爱"]

    def test_save_external_with_embedding(self, db, fake_collection, patch_embeddings):
        item = ingest.ingest_external(
            source="bangumi", external_id="302", title="某部动画",
            content="这是一段用于切分并生成向量的动画简介文字。" * 30, db=db,
        )
        assert len(item.chunks) > 0
        assert len(fake_collection.vectors) == len(item.chunks)

    def test_save_external_no_content(self, db, fake_collection, patch_embeddings):
        item = ingest.ingest_external(
            source="bangumi", external_id="303", title="仅有标题", db=db,
        )
        assert item.chunks == []
        assert len(fake_collection.vectors) == 0


class TestDeclarativeConnector:
    CONFIG = {
        "name": "my-api",
        "display_name": "我的API",
        "base_url": "https://api.example.com",
        "search_endpoint": "/search?q={query}",
        "result_path": "data.items",
        "field_map": {
            "title": "title",
            "external_id": "id",
            "description": "summary",
            "image_url": "cover",
            "rating": "score",
            "tags": "tags",
        },
    }
    SAMPLE_RESP = {
        "data": {
            "items": [
                {
                    "id": "abc123",
                    "title": "示例结果",
                    "summary": "一段描述。",
                    "cover": "https://img.example.com/1.jpg",
                    "score": 8.5,
                    "tags": ["a", "b"],
                },
                {"id": "def", "title": "第二条"},
            ]
        }
    }

    def test_config_validation(self):
        with pytest.raises(ValueError):
            DeclarativeConnector({"name": "bad", "base_url": "http://x", "search_endpoint": "/s", "field_map": {}})
        with pytest.raises(ValueError):
            DeclarativeConnector({"name": "bad", "search_endpoint": "/s", "field_map": {"title": "t", "external_id": "i"}})

    def test_search_with_field_mapping(self, monkeypatch):
        conn = DeclarativeConnector(self.CONFIG)
        monkeypatch.setattr("httpx.get", lambda url, headers=None, timeout=None: _FakeResp(200, self.SAMPLE_RESP))
        results = conn.search("关键词")
        assert len(results) == 2
        r0 = results[0]
        assert r0.source == "my-api"
        assert r0.title == "示例结果"
        assert r0.external_id == "abc123"
        assert r0.description == "一段描述。"
        assert r0.rating == 8.5
        assert r0.tags == ["a", "b"]
        assert r0.raw is self.SAMPLE_RESP["data"]["items"][0]

    def test_search_nested_result_path(self, monkeypatch):
        conn = DeclarativeConnector(self.CONFIG)
        monkeypatch.setattr("httpx.get", lambda url, headers=None, timeout=None: _FakeResp(200, {"results": [{"id": "1", "title": "x"}]}))
        results = conn.search("查询")
        assert len(results) == 0  # result_path=data.items 不匹配，安全返回空

    def test_search_api_error(self, monkeypatch):
        conn = DeclarativeConnector(self.CONFIG)
        monkeypatch.setattr("httpx.get", lambda url, headers=None, timeout=None: _FakeResp(500, {}))
        with pytest.raises(ConnectorError):
            conn.search("查询")

    def test_normalize(self):
        conn = DeclarativeConnector(self.CONFIG)
        fields = conn.normalize(self.SAMPLE_RESP["data"]["items"][0])
        assert fields["source"] == "my-api"
        assert fields["title"] == "示例结果"
        assert fields["external_id"] == "abc123"
        assert fields["type"] == "external_ref"
        assert fields["tags"] == ["a", "b"]

    def test_headers_placeholder_resolved(self, monkeypatch):
        config = dict(self.CONFIG)
        config["headers"] = {"Authorization": "{api_key}"}
        config["api_key"] = "secret123"
        conn = DeclarativeConnector(config)
        captured = {}

        def fake_get(url, headers=None, timeout=None):
            captured["headers"] = headers
            return _FakeResp(200, {"results": [{"id": "1", "title": "x"}]})

        monkeypatch.setattr("httpx.get", fake_get)
        conn.search("q")
        assert captured["headers"]["Authorization"] == "secret123"


class _FakeResp:
    def __init__(self, status_code, json_payload):
        self.status_code = status_code
        self._json = json_payload

    def json(self):
        return self._json
