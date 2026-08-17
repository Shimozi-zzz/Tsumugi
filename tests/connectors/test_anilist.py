"""AniList Connector 测试（Phase 11-A）

覆盖：正常搜索/详情、空结果、HTTP error、GraphQL error、timeout、
malformed JSON、缺字段、null 字段、characters / staff / relations。
"""
import pytest
import httpx

from app.connectors import registry
from app.connectors.anilist.connector import (
    AniListConnector, _format_date, _pick_title, _strip_html,
)
from app.connectors.base import ConnectorError, ItemDetail, RateLimitError, SearchResult


MEDIA = {
    "id": 9253, "type": "ANIME", "format": "TV",
    "title": {"romaji": "Steins;Gate", "english": "Steins;Gate", "native": "シュタインズ・ゲート"},
    "description": "<p>Mad scientist desc.</p>", "coverImage": {"extraLarge": "https://x/l.png", "large": "https://x/m.png"},
    "bannerImage": "https://x/b.png", "averageScore": 90,
    "genres": ["Sci-Fi", "Thriller"], "tags": [{"name": "time travel"}],
    "status": "FINISHED", "episodes": 24, "startDate": {"year": 2011, "month": 4, "day": 5},
    "characters": {"edges": [{
        "role": "MAIN",
        "node": {"id": 1, "name": {"full": "Makise Kurisu", "native": "牧瀬紅莉栖"},
                 "image": {"large": "https://x/k.png"}, "description": "<p>Neuroscientist</p>"},
        "voiceActors": [{"id": 10, "name": {"full": "Asami Imai"}}],
    }]},
    "staff": {"edges": [{"role": "Director", "node": {"id": 5, "name": {"full": "Takuya Sato"}}}]},
    "relations": {"edges": [{"relationType": "SEQUEL",
                             "node": {"id": 999, "type": "ANIME",
                                      "title": {"romaji": "Steins;Gate 0"}}}]},
}

GRAPHQL_OK = {"data": {"Page": {"media": [MEDIA]}}}
DETAIL_OK = {"data": {"Media": MEDIA}}


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


def _mock(monkeypatch, payload, status=200):
    def fake_post(url, json_body=None, **kw):
        return _FakeResp(status, payload)
    monkeypatch.setattr("app.connectors.anilist.connector.http_post", fake_post)
    return fake_post


def _conn(monkeypatch, payload, status=200):
    _mock(monkeypatch, payload, status)
    conn = AniListConnector()
    monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
    monkeypatch.setattr(conn._cache, "set", lambda k, v: None)
    return conn


class TestUtils:
    def test_pick_title_prefers_romaji(self):
        t = {"romaji": "Steins;Gate", "english": "Steins;Gate", "native": "ネイティブ"}
        assert _pick_title(t) == ("Steins;Gate", "ネイティブ")

    def test_pick_title_null(self):
        assert _pick_title(None) == ("", "")
        assert _pick_title({"romaji": None, "english": ""}) == ("", "")

    def test_strip_html(self):
        assert _strip_html("<p>Hello &amp; <b>world</b></p>") == "Hello & world"
        assert _strip_html(None) == ""
        assert _strip_html("   ") == ""

    def test_format_date(self):
        assert _format_date({"year": 2011, "month": 4, "day": 5}) == "2011-04-05"
        assert _format_date({"year": 2011, "month": 4}) == "2011-04"
        assert _format_date({"year": 2011}) == "2011"
        assert _format_date(None) == ""
        assert _format_date({}) == ""


class TestSearch:
    def test_empty_query(self):
        conn = AniListConnector()
        assert conn.search("  ") == []

    def test_normal_search(self, monkeypatch):
        conn = _conn(monkeypatch, GRAPHQL_OK)
        results = conn.search("Steins")
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, SearchResult)
        assert r.source == "anilist"
        assert r.title == "Steins;Gate"
        assert r.subtitle == "シュタインズ・ゲート"
        assert r.external_id == "9253"
        assert r.year == 2011
        assert r.type == "anime"
        assert r.rating == 9.0  # 90/10
        assert r.image_url == "https://x/l.png"
        assert r.tags == ["time travel"]
        assert r.external_url == "https://anilist.co/anime/9253"

    def test_empty_results(self, monkeypatch):
        conn = _conn(monkeypatch, {"data": {"Page": {"media": []}}})
        assert conn.search("nothing") == []

    def test_http_error(self, monkeypatch):
        conn = _conn(monkeypatch, "boom", status=500)
        with pytest.raises(ConnectorError, match="500"):
            conn.search("x")

    def test_rate_limit(self, monkeypatch):
        conn = _conn(monkeypatch, "rate", status=429)
        with pytest.raises(RateLimitError):
            conn.search("x")

    def test_graphql_error(self, monkeypatch):
        conn = _conn(monkeypatch, {"errors": [{"message": "boom"}]})
        with pytest.raises(ConnectorError, match="boom"):
            conn.search("x")

    def test_timeout(self, monkeypatch):
        def boom(url, json_body=None, **kw):
            raise httpx.ConnectError("timeout")
        monkeypatch.setattr("app.connectors.anilist.connector.http_post", boom)
        conn = AniListConnector()
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
        with pytest.raises(ConnectorError):
            conn.search("x")

    def test_malformed_json(self, monkeypatch):
        conn = _conn(monkeypatch, "not-json")
        with pytest.raises(ConnectorError, match="无法解析"):
            conn.search("x")

    def test_null_and_missing_fields(self, monkeypatch):
        conn = _conn(monkeypatch, {"data": {"Page": {"media": [{
            "id": 1, "type": "MANGA", "title": {"romaji": "T", "english": None, "native": None},
            "coverImage": None, "averageScore": None, "genres": None,
            "tags": None, "startDate": None, "description": None,
        }]}}})
        r = conn.search("x")[0]
        assert r.title == "T"
        assert r.year is None
        assert r.rating is None
        assert r.tags == []
        assert r.image_url is None
        assert r.type == "manga"


class TestGetDetail:
    def test_normal_detail(self, monkeypatch):
        conn = _conn(monkeypatch, DETAIL_OK)
        d = conn.get_detail("9253")
        assert isinstance(d, ItemDetail)
        assert d.title == "Steins;Gate"
        assert d.genres == ["Sci-Fi", "Thriller"]
        assert d.background == "https://x/b.png"
        assert d.status == "FINISHED"
        assert d.episodes == 24
        assert d.metadata["date"] == "2011-04-05"
        assert d.metadata["rating"] == 9.0

    def test_detail_characters(self, monkeypatch):
        conn = _conn(monkeypatch, DETAIL_OK)
        chars = conn.get_detail("9253").metadata["characters"]
        assert len(chars) == 1
        c = chars[0]
        assert c["name"] == "Makise Kurisu"
        assert c["relation"] == "MAIN"
        assert c["summary"] == "Neuroscientist"
        assert c["actors"] == ["Asami Imai"]
        assert c["image_url"] == "https://x/k.png"

    def test_detail_staff(self, monkeypatch):
        conn = _conn(monkeypatch, DETAIL_OK)
        staff = conn.get_detail("9253").metadata["staff"]
        assert staff == [{"name": "Takuya Sato", "role": "Director",
                          "source": "anilist", "external_id": "5"}]

    def test_detail_relations(self, monkeypatch):
        conn = _conn(monkeypatch, DETAIL_OK)
        rels = conn.get_detail("9253").metadata["relations"]
        assert rels == [{"relation": "SEQUEL", "title": "Steins;Gate 0",
                         "external_id": "999", "source": "anilist"}]

    def test_detail_missing(self, monkeypatch):
        conn = _conn(monkeypatch, {"data": {"Media": None}})
        with pytest.raises(ConnectorError, match="未找到"):
            conn.get_detail("99999")

    def test_detail_null_optional_fields(self, monkeypatch):
        conn = _conn(monkeypatch, {"data": {"Media": {
            "id": 1, "type": "ANIME", "title": {"romaji": "X", "english": None, "native": None},
            "description": None, "coverImage": None, "bannerImage": None, "averageScore": None,
            "genres": None, "tags": None, "status": None, "episodes": None, "startDate": None,
            "characters": None, "staff": None, "relations": None,
        }}})
        d = conn.get_detail("1")
        assert d.genres == []
        assert d.background is None
        assert d.status is None
        assert d.episodes is None
        assert d.staff == []
        assert d.relations == []
        assert d.metadata["characters"] == []


class TestDiscover:
    def test_discover_registers_anilist(self):
        try:
            names = registry.discover()
            conn = registry.get_connector("anilist")
            assert "anilist" in names
            assert conn is not None
            assert conn.manifest.display_name == "AniList"
            assert conn.manifest.base_url == "https://graphql.anilist.co"
            assert "search" in conn.manifest.capabilities
            assert "get_detail" in conn.manifest.capabilities
        finally:
            registry.unregister("anilist")
