"""Jikan (MyAnimeList) Connector 测试（Phase 12-B）

覆盖：search（anime+manga）/ detail / empty / HTTP 400/404/429/500 / timeout /
malformed / missing / null / characters / staff / relations / studios / season / external。
"""
import pytest
import httpx

from app.connectors import registry
from app.connectors.base import ConnectorError, ItemDetail, RateLimitError, SearchResult
from app.connectors.jikan.connector import JikanConnector, _media_to_detail, _media_to_search_result


ANIME = {
    "mal_id": 9253, "url": "https://myanimelist.net/anime/9253",
    "title": "Steins;Gate", "title_english": "Steins;Gate", "title_japanese": "シュタインズ・ゲート",
    "type": "TV", "aired": {"from": "2011-04-06T00:00:00+00:00"}, "score": 9.09,
    "synopsis": "<p>Mad scientist desc.</p>", "images": {"jpg": {"large_image_url": "https://x/l.png"}},
    "genres": [{"name": "Sci-Fi"}], "themes": [{"name": "Time Travel"}], "demographics": [{"name": "Seinen"}],
}

MANGA = {
    "mal_id": 47517, "url": "https://myanimelist.net/manga/47517",
    "title": "Steins;Gate", "title_english": "Steins;Gate", "type": "Manga",
    "published": {"from": "2009-10-23T00:00:00+00:00"}, "score": 8.5,
    "synopsis": "Manga", "images": {"jpg": {"image_url": "https://x/m.png"}}, "genres": [{"name": "Sci-Fi"}],
}

DETAIL = {
    "mal_id": 9253, "title": "Steins;Gate", "images": {"jpg": {"large_image_url": "https://x/l.png"}},
    "genres": [{"name": "Sci-Fi"}], "status": "Finished Airing", "episodes": 24,
    "aired": {"from": "2011-04-06T00:00:00+00:00"}, "score": 9.09,
    "season": "Spring", "year": 2011, "studios": [{"name": "White Fox"}],
    "external": [{"name": "ANN", "url": "https://x/ann"}],
    "characters": [{"character": {"mal_id": 1, "name": "Makise Kurisu",
                                   "images": {"jpg": {"large_image_url": "https://x/k.png"}}},
                    "role": "Main", "voice_actors": [{"person": {"name": "Asami Imai"}}]}],
    "staff": [{"person": {"mal_id": 5, "name": "Takuya Sato"}, "positions": ["Director"]}],
    "relations": [{"relation": "Sequel", "entry": [{"mal_id": 999, "name": "Steins;Gate 0"}]}],
}


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


def _conn(monkeypatch, handler):
    def fake_get(url, **kw):
        return handler(url, kw)
    monkeypatch.setattr("app.connectors.jikan.connector.http_get", fake_get)
    conn = JikanConnector()
    monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
    monkeypatch.setattr(conn._cache, "set", lambda k, v: None)
    return conn


def _search_handler():
    def handler(url, kw):
        if "/manga" in url:
            return _FakeResp(200, {"data": [MANGA]})
        return _FakeResp(200, {"data": [ANIME]})
    return handler


class TestSearch:
    def test_empty_query(self):
        assert JikanConnector().search("  ") == []

    def test_normal_search_anime_and_manga(self, monkeypatch):
        conn = _conn(monkeypatch, _search_handler())
        results = conn.search("Steins")
        assert len(results) == 2
        anime = next(r for r in results if r.type == "anime")
        manga = next(r for r in results if r.type == "manga")
        assert anime.source == "jikan"
        assert anime.title == "Steins;Gate"
        assert anime.year == 2011
        assert anime.rating == 9.09
        assert anime.tags == ["Sci-Fi", "Time Travel", "Seinen"]
        assert anime.external_url.startswith("https://myanimelist.net/anime/")
        assert manga.type == "manga"
        assert manga.year == 2009

    def test_empty_results(self, monkeypatch):
        conn = _conn(monkeypatch, lambda url, kw: _FakeResp(200, {"data": []}))
        assert conn.search("nothing") == []

    def test_http_error(self, monkeypatch):
        conn = _conn(monkeypatch, lambda url, kw: _FakeResp(500, "boom"))
        with pytest.raises(ConnectorError, match="500"):
            conn.search("x")

    def test_rate_limit(self, monkeypatch):
        conn = _conn(monkeypatch, lambda url, kw: _FakeResp(429, "rate"))
        with pytest.raises(RateLimitError):
            conn.search("x")

    def test_timeout(self, monkeypatch):
        def boom(url, **kw):
            raise httpx.ConnectError("timeout")
        monkeypatch.setattr("app.connectors.jikan.connector.http_get", boom)
        conn = JikanConnector()
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
        with pytest.raises(ConnectorError):
            conn.search("x")

    def test_malformed_json(self, monkeypatch):
        conn = _conn(monkeypatch, lambda url, kw: _FakeResp(200, "not-json"))
        with pytest.raises(ConnectorError, match="无法解析"):
            conn.search("x")


class TestGetDetail:
    def test_anime_detail(self, monkeypatch):
        def handler(url, kw):
            if "/anime/9253/full" in url:
                return _FakeResp(200, {"data": DETAIL})
            return _FakeResp(404, "nf")
        conn = _conn(monkeypatch, handler)
        d = conn.get_detail("9253")
        assert isinstance(d, ItemDetail)
        assert d.title == "Steins;Gate"
        assert d.status == "Finished Airing"
        assert d.episodes == 24
        assert d.genres == ["Sci-Fi"]
        assert d.metadata["season"] == "Spring"
        assert d.metadata["studios"] == ["White Fox"]
        assert len(d.metadata["external_links"]) == 1

    def test_detail_characters(self, monkeypatch):
        def handler(url, kw):
            return _FakeResp(200, {"data": DETAIL})
        conn = _conn(monkeypatch, handler)
        chars = conn.get_detail("9253").metadata["characters"]
        assert len(chars) == 1
        assert chars[0]["name"] == "Makise Kurisu"
        assert chars[0]["relation"] == "Main"
        assert chars[0]["actors"] == ["Asami Imai"]

    def test_detail_staff(self, monkeypatch):
        conn = _conn(monkeypatch, lambda url, kw: _FakeResp(200, {"data": DETAIL}))
        staff = conn.get_detail("9253").metadata["staff"]
        assert staff[0]["name"] == "Takuya Sato"
        assert staff[0]["role"] == "Director"
        assert staff[0]["source"] == "jikan"
        assert staff[0]["external_id"] == "5"
        assert staff[0]["credit_order"] == 0

    def test_detail_relations(self, monkeypatch):
        conn = _conn(monkeypatch, lambda url, kw: _FakeResp(200, {"data": DETAIL}))
        rels = conn.get_detail("9253").metadata["relations"]
        assert rels[0]["relation"] == "Sequel"
        assert rels[0]["title"] == "Steins;Gate 0"
        assert rels[0]["external_id"] == "999"

    def test_manga_fallback_when_anime_404(self, monkeypatch):
        manga_detail = dict(DETAIL, mal_id=47517, type="Manga")
        def handler(url, kw):
            if "/anime/47517/full" in url:
                return _FakeResp(404, "nf")
            return _FakeResp(200, {"data": manga_detail})
        conn = _conn(monkeypatch, handler)
        d = conn.get_detail("47517")
        assert d.metadata["type"] == "manga"

    def test_detail_not_found(self, monkeypatch):
        conn = _conn(monkeypatch, lambda url, kw: _FakeResp(404, "nf"))
        with pytest.raises(ConnectorError, match="未找到"):
            conn.get_detail("99999")

    def test_detail_null_fields(self, monkeypatch):
        null = {"mal_id": 1, "title": "X", "images": None, "genres": None, "status": None,
                "episodes": None, "staff": None, "relations": None, "characters": None,
                "external": None, "studios": None}
        conn = _conn(monkeypatch, lambda url, kw: _FakeResp(200, {"data": null}))
        d = conn.get_detail("1")
        assert d.genres == []
        assert d.staff == []
        assert d.relations == []
        assert d.metadata["characters"] == []
        assert d.episodes is None


class TestDiscover:
    def test_discover_registers_jikan(self):
        try:
            names = registry.discover()
            conn = registry.get_connector("jikan")
            assert "jikan" in names
            assert conn is not None
            assert conn.manifest.display_name == "Jikan / MyAnimeList"
            assert "search" in conn.manifest.capabilities
            assert "get_detail" in conn.manifest.capabilities
        finally:
            registry.unregister("jikan")
