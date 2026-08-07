"""VNDB Connector 测试：POST body 结构、search/get_detail/normalize、角色归一化"""
import pytest

from app.connectors import registry
from app.connectors.base import ConnectorError, ItemDetail, RateLimitError, SearchResult
from app.connectors.vndb.connector import VndbConnector, _strip_bbcode, _characters_to_normalized


VN_V2002 = {
    "id": "v2002", "title": "STEINS;GATE", "alttitle": "シュタインズ・ゲート",
    "image": {"url": "https://t.vndb.org/cv/19/77819.jpg"},
    "description": "[b]-Decide The Fate Of All Mankind-[/b]\nCAN YOU CHANGE THE COURSE OF FATE?",
    "rating": 90.2, "released": "2011-06-16",
    "developers": [{"name": "Nitroplus"}],
    "tags": [{"name": "ADV", "category": "tech"}, {"name": "Romance", "category": "cont"}],
}

CHAR_CURISU = {
    "id": "c6487", "name": "Makise Kurisu",
    "image": {"url": "https://t.vndb.org/ch/34/97234.jpg"},
    "description": "[b]A genius[/b] neuroscience researcher.",
    "vns": [{"role": "primary", "spoiler": 0, "title": "STEINS;GATE"}],
}
CHAR_MAYURI = {
    "id": "c6491", "name": "Shiina Mayuri",
    "image": {"url": "https://t.vndb.org/ch/95/97195.jpg"},
    "description": "Childhood friend.",
    "vns": [{"role": "main", "spoiler": 0, "title": "STEINS;GATE"}],
}


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = payload if isinstance(payload, str) else ""

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


def _mock_http(monkeypatch, vn_resp, char_resp=None):
    def fake_post(url, json_body=None, **kw):
        if url.endswith("/character"):
            return _FakeResp(200, {"more": False, "results": char_resp or []})
        return _FakeResp(200, {"more": False, "results": vn_resp})
    monkeypatch.setattr("app.connectors.vndb.connector.http_post", fake_post)
    return fake_post


class TestUtils:
    def test_strip_bbcode(self):
        assert _strip_bbcode("[b]bold[/b] and [i]it[/i] text") == "bold and it text"
        assert _strip_bbcode("[url=https://x]link[/url]") == "link"
        assert _strip_bbcode(None) == ""

    def test_characters_normalized(self):
        chars = _characters_to_normalized([CHAR_CURISU, CHAR_MAYURI])
        by_name = {c["name"]: c for c in chars}
        assert by_name["Makise Kurisu"]["relation"] == "主要角色"
        assert by_name["Makise Kurisu"]["actors"] == []
        assert by_name["Makise Kurisu"]["summary"] == "A genius neuroscience researcher."
        assert by_name["Shiina Mayuri"]["relation"] == "主角"


class TestSearch:
    def test_empty_query(self):
        conn = VndbConnector()
        assert conn.search("  ") == []

    def test_search_maps_real_response(self, monkeypatch):
        _mock_http(monkeypatch, [VN_V2002, {"id": "v17102", "title": "STEINS;GATE 0", "rating": 81.0,
                                            "image": {"url": "x.jpg"}, "tags": []}])
        conn = VndbConnector()
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
        monkeypatch.setattr(conn._cache, "set", lambda k, v: None)
        results = conn.search("Steins;Gate")
        assert len(results) == 2
        r0 = results[0]
        assert isinstance(r0, SearchResult)
        assert r0.source == "vndb"
        assert r0.external_id == "v2002"
        assert r0.title == "STEINS;GATE"
        assert r0.rating == 9.0  # 90.2/10 → 0-10 标度
        assert r0.tags == ["ADV", "Romance"]
        assert r0.description == "-Decide The Fate Of All Mankind-\nCAN YOU CHANGE THE COURSE OF FATE?"  # BBCode 已清洗
        assert r0.image_url == "https://t.vndb.org/cv/19/77819.jpg"

    def test_search_uses_post_body(self, monkeypatch):
        captured = {}
        def fake_post(url, json_body=None, **kw):
            captured["body"] = json_body
            return _FakeResp(200, {"results": []})
        monkeypatch.setattr("app.connectors.vndb.connector.http_post", fake_post)
        conn = VndbConnector()
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
        conn.search("Steins")
        assert captured["body"]["filters"] == ["search", "=", "Steins"]
        assert captured["body"]["fields"].startswith("id,title")
        assert captured["body"]["sort"] == "searchrank"

    def test_api_error(self, monkeypatch):
        def fake_post(url, json_body=None, **kw):
            return _FakeResp(500, "boom")
        monkeypatch.setattr("app.connectors.vndb.connector.http_post", fake_post)
        conn = VndbConnector()
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
        with pytest.raises(ConnectorError, match="500"):
            conn.search("x")

    def test_rate_limit(self, monkeypatch):
        def fake_post(url, json_body=None, **kw):
            return _FakeResp(429, "rate")
        monkeypatch.setattr("app.connectors.vndb.connector.http_post", fake_post)
        conn = VndbConnector()
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
        with pytest.raises(RateLimitError):
            conn.search("x")


class TestGetDetail:
    def test_detail_includes_characters(self, monkeypatch):
        _mock_http(monkeypatch, [VN_V2002], [CHAR_CURISU, CHAR_MAYURI])
        conn = VndbConnector()
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
        monkeypatch.setattr(conn._cache, "set", lambda k, v: None)
        d = conn.get_detail("v2002")
        assert isinstance(d, ItemDetail)
        assert d.title == "STEINS;GATE"
        assert d.metadata["rating"] == 9.0
        assert d.metadata["developers"] == ["Nitroplus"]
        chars = d.metadata["characters"]
        assert len(chars) == 2
        assert chars[0]["name"] == "Makise Kurisu"
        assert chars[0]["relation"] == "主要角色"
        assert chars[0]["image_url"].startswith("https://t.vndb.org")

    def test_detail_missing(self, monkeypatch):
        _mock_http(monkeypatch, [])
        conn = VndbConnector()
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
        with pytest.raises(ConnectorError, match="未找到"):
            conn.get_detail("v99999")

    def test_characters_failure_degrades(self, monkeypatch):
        def fake_post(url, json_body=None, **kw):
            if url.endswith("/character"):
                return _FakeResp(400, "bad")
            return _FakeResp(200, {"results": [VN_V2002]})
        monkeypatch.setattr("app.connectors.vndb.connector.http_post", fake_post)
        conn = VndbConnector()
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
        d = conn.get_detail("v2002")
        assert d.metadata["characters"] == []


class TestNormalize:
    def test_normalize_maps_fields(self):
        conn = VndbConnector()
        raw = dict(VN_V2002)
        raw["characters"] = [CHAR_CURISU]
        fields = conn.normalize(raw)
        assert fields["title"] == "STEINS;GATE"
        assert fields["type"] == "external_ref"
        assert fields["source"] == "vndb"
        assert fields["external_id"] == "v2002"
        assert "Decide The Fate" in fields["content"]
        assert fields["tags"] == ["ADV", "Romance"]
        assert fields["raw_metadata"] is raw


class TestCacheNamespace:
    """第三源接入暴露的 bug：所有 Connector 共用同一缓存表 + 相同 key 前缀会互相
    污染（vndb 读到了 moegirl 的 search 缓存 → external_id 为空）。"""

    def test_connectors_do_not_pollute_each_other(self, tmp_path):
        from app.connectors.base import RequestCache
        c1 = RequestCache(db_path=str(tmp_path / "c.db"), namespace="bangumi")
        c2 = RequestCache(db_path=str(tmp_path / "c.db"), namespace="moegirl")
        c3 = RequestCache(db_path=str(tmp_path / "c.db"), namespace="vndb")
        c1.set("search:命运石之门", [{"id": "3154", "title": "命运石之门"}])
        c2.set("search:命运石之门", [{"pageid": 21573, "title": "命运石之门系列"}])
        c3.set("search:命运石之门", [{"id": "v2002", "title": "STEINS;GATE"}])
        assert c1.get("search:命运石之门")[0]["id"] == "3154"
        assert c2.get("search:命运石之门")[0]["pageid"] == 21573
        assert c3.get("search:命运石之门")[0]["id"] == "v2002"

    def test_namespace_default_no_prefix(self, tmp_path):
        from app.connectors.base import RequestCache
        c = RequestCache(db_path=str(tmp_path / "d.db"))
        c.set("k", 1)
        assert c.get("k") == 1


class TestDiscover:
    def test_discover_registers_vndb(self):
        try:
            names = registry.discover()
            conn = registry.get_connector("vndb")
            assert "vndb" in names
            assert conn is not None
            assert conn.manifest.display_name == "VNDB"
            assert conn.manifest.base_url == "https://api.vndb.org/kana"
            assert conn.manifest.rate_limit["requests_per_minute"] == 40
            assert "get_detail" in conn.manifest.capabilities
        finally:
            registry.unregister("vndb")
