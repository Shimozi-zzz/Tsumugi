"""萌娘百科 Connector 测试：search/get_detail/normalize（真实格式 mock 响应）

mock 数据基于 2026-08-06 对 zh.moegirl.org.cn 的真实抓取：
- 搜索用 generator=search（list=search 被禁），返回 pages dict；
- 详情用 prop=info|pageimages|categories|extracts，含维护类分类需过滤；
- wikitext Infobox 兜底路径用一份贴近萌娘百科《人物信息》模板的样例。
"""
import json

import pytest

from app.connectors.base import ConnectorError, ItemDetail, SearchResult
from app.connectors.moegirl.connector import (
    MoegirlConnector,
    _first_section,
    _parse_infobox,
    _strip_wikitext,
)


# ---------------------------------------------------------------- 真实格式 mock 数据

SEARCH_RESP = {
    "batchcomplete": "",
    "continue": {"gsroffset": 5, "continue": "gsroffset||"},
    "query": {
        "pages": {
            "123": {
                "pageid": 123, "ns": 0, "title": "初音未来(世界计划)", "index": 2,
                "thumbnail": {"source": "https://storage.moegirl.org.cn/moegirl/commons/x/xx/world.jpg", "width": 200, "height": 200},
                "extract": "《初音未来：世界计划》是一款以初音未来等VOCALOID角色为主题的音乐节奏游戏。",
            },
            "1399": {
                "pageid": 1399, "ns": 0, "title": "初音未来", "index": 1,
                "thumbnail": {"source": "https://storage.moegirl.org.cn/moegirl/commons/f/f7/MikuV6_main.jpeg", "width": 480, "height": 690},
                "extract": "初音未来（日语：初音（はつね）ミク，平文式罗马字：Hatsune Miku）是由Crypton Future Media株式会社企划、开发、贩卖，可供YAMAHA的VOCALOID歌声合成引擎和Crypton自主研发的NT引擎使用的歌声库软件及其拟人化形象。",
            },
        }
    },
}

DETAIL_RESP = {
    "batchcomplete": "",
    "query": {
        "pages": {
            "1399": {
                "pageid": 1399, "ns": 0, "title": "初音未来", "length": 86521,
                "thumbnail": {"source": "https://storage.moegirl.org.cn/moegirl/commons/f/f7/MikuV6_main.jpeg", "width": 480, "height": 690},
                "extract": "初音未来（日语：初音（はつね）ミク，平文式罗马字：Hatsune Miku）是由Crypton Future Media株式会社企划、开发、贩卖，可供YAMAHA的VOCALOID歌声合成引擎和Crypton自主研发的NT引擎使用的歌声库软件及其拟人化形象。\n初音未来的日文与英文简称分别为“ミク”与“Miku”，而中文社区则经常简称为“初音”。",
                "categories": [
                    {"ns": 14, "title": "Category:8月31日"},
                    {"ns": 14, "title": "Category:M形刘海"},
                    {"ns": 14, "title": "Category:VOCALOID角色"},
                    {"ns": 14, "title": "Category:使用标题替换的页面"},
                    {"ns": 14, "title": "Category:分离袖子"},
                    {"ns": 14, "title": "Category:双马尾"},
                    {"ns": 14, "title": "Category:发饰"},
                    {"ns": 14, "title": "Category:处女座"},
                    {"ns": 14, "title": "Category:带有无法存档的失效链接的条目"},
                ],
            }
        }
    },
}

# 贴近萌娘百科《人物信息》模板的真实风格 wikitext（含嵌套模板/链接/注释）
MIKU_WIKITEXT = """{{人物信息
|image = MikuV6_main.jpeg
|caption = 初音未来
|本名 = 初音ミク（はつね ミク）
|发色 = 绿
|瞳色 = 绿
|身高 = 158cm
|年龄 = 16岁
|生日 = 8月31日
|星座 = 处女座
|萌点 = [[双马尾]]、[[发饰]]、[[绿发]]、[[呆毛]]
|出身地区 = 日本
|所属团体 = [[Crypton Future Media]]
|相关角色 = [[镜音铃]]、[[镜音连]]、[[巡音流歌]]
|简介 = 初音未来是Crypton Future Media开发的'''VOCALOID'''歌声合成软件及其拟人化形象。<ref>官方设定资料</ref>
}}

'''初音未来'''（日语：初音（はつね）ミク）是由Crypton Future Media株式会社企划、开发、贩卖的歌声库软件。

== 设定 ==
初音未来的生日是8月31日。
"""


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _mock_http(monkeypatch, payload):
    monkeypatch.setattr(
        "app.connectors.base.httpx.get",
        lambda url, **kwargs: _FakeResp(200, payload),
    )


# ---------------------------------------------------------------- wikitext 解析工具

class TestWikitextHelpers:
    def test_parse_infobox_fields(self):
        info = _parse_infobox(MIKU_WIKITEXT)
        assert info["本名"] == "初音ミク（はつね ミク）"
        assert info["萌点"] == "[[双马尾]]、[[发饰]]、[[绿发]]、[[呆毛]]"
        assert info["生日"] == "8月31日"
        assert "简介" in info

    def test_parse_infobox_ignores_non_infobox(self):
        text = "{{需要维护}}\n| foo = bar\n\n{{人物信息\n|本名 = 初音ミク\n}}"
        info = _parse_infobox(text)
        assert info.get("本名") == "初音ミク"

    def test_strip_wikitext(self):
        text = "'''初音未来'''（日语：初音<ref>ref</ref>）是[[VOCALOID|歌声合成软件]]。<!-- 注释 -->{{模板}}"
        out = _strip_wikitext(text)
        assert "初音未来" in out
        assert "歌声合成软件" in out
        assert "ref" not in out
        assert "注释" not in out
        assert "模板" not in out

    def test_first_section(self):
        assert _first_section("导言\n== 章节 ==") == "导言\n"
        assert _first_section("无标题全文本") == "无标题全文本"


# ---------------------------------------------------------------- search

class TestSearch:
    def test_empty_query(self):
        conn = MoegirlConnector()
        assert conn.search("  ") == []

    def test_search_sorted_and_mapped(self, monkeypatch):
        conn = MoegirlConnector()
        _mock_http(monkeypatch, SEARCH_RESP)
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
        results = conn.search("初音未来")
        assert len(results) == 2
        assert results[0].external_id == "1399"  # 按 index 排序，初音未来在前
        r = results[0]
        assert isinstance(r, SearchResult)
        assert r.source == "moegirl"
        assert r.title == "初音未来"
        assert r.external_id == "1399"
        assert r.image_url and r.image_url.startswith("https://")
        assert "Crypton" in (r.description or "")

    def test_search_uses_cache(self, monkeypatch):
        conn = MoegirlConnector()
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: [
            {"pageid": 1399, "ns": 0, "title": "初音未来", "index": 1}
        ])
        results = conn.search("初音未来")
        assert len(results) == 1
        assert results[0].title == "初音未来"

    def test_search_api_error_raises(self, monkeypatch):
        conn = MoegirlConnector()
        _mock_http(monkeypatch, {"error": {"code": "internal_api_error", "info": "出错啦"}})
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
        with pytest.raises(ConnectorError, match="出错啦"):
            conn.search("x")

    def test_search_notallowed_message(self, monkeypatch):
        conn = MoegirlConnector()
        _mock_http(monkeypatch, {"error": {"code": "action-notallowed", "info": "Unauthorized"}})
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
        with pytest.raises(ConnectorError, match="拒绝访问"):
            conn.search("x")


# ---------------------------------------------------------------- get_detail

class TestGetDetail:
    def test_detail_maps_fields(self, monkeypatch):
        conn = MoegirlConnector()
        _mock_http(monkeypatch, DETAIL_RESP)
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
        d = conn.get_detail("1399")
        assert isinstance(d, ItemDetail)
        assert d.title == "初音未来"
        assert d.external_id == "1399"
        assert "Crypton" in d.description
        assert d.image_url and d.image_url.startswith("https://")
        # 维护类分类被过滤
        cats = d.metadata["categories"]
        assert "双马尾" in cats
        assert "VOCALOID角色" in cats
        assert "使用标题替换的页面" not in cats
        assert "分离袖子" not in cats
        assert "带有无法存档的失效链接的条目" not in cats

    def test_detail_missing_page(self, monkeypatch):
        conn = MoegirlConnector()
        _mock_http(monkeypatch, {"query": {"pages": {"9999": {"pageid": 9999, "ns": 0, "title": "不存在", "missing": ""}}}})
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
        with pytest.raises(ConnectorError, match="未找到"):
            conn.get_detail("9999")


# ---------------------------------------------------------------- normalize

class TestNormalize:
    def test_normalize_structured_fields(self):
        conn = MoegirlConnector()
        page = DETAIL_RESP["query"]["pages"]["1399"]
        fields = conn.normalize(page)
        assert fields["title"] == "初音未来"
        assert fields["type"] == "external_ref"
        assert fields["source"] == "moegirl"
        assert fields["external_id"] == "1399"
        assert "Crypton" in fields["content"]
        assert fields["image_url"].startswith("https://")
        assert "双马尾" in fields["tags"]
        assert "使用标题替换的页面" not in fields["tags"]

    def test_normalize_wikitext_fallback(self):
        conn = MoegirlConnector()
        raw = {
            "pageid": 999, "title": "初音未来",
            "wikitext": MIKU_WIKITEXT,
        }
        fields = conn.normalize(raw)
        assert fields["external_id"] == "999"
        assert "VOCALOID" in fields["content"]
        # Infobox 简介优先；无结构化封面时用 image 字段
        assert "初音未来是Crypton" in fields["content"]
        # 萌点清洗为纯文本标签
        assert "双马尾" in fields["tags"]
        assert "发饰" in fields["tags"]
        assert fields["tags"] == ["双马尾", "发饰", "绿发", "呆毛"]

    def test_normalize_empty(self):
        conn = MoegirlConnector()
        fields = conn.normalize({"pageid": 1, "title": ""})
        assert fields["external_id"] == "1"
        assert fields["content"] == ""
        assert fields["tags"] == []

    def test_normalize_infobox_only_for_image(self):
        conn = MoegirlConnector()
        raw = {
            "pageid": 1, "title": "测试",
            "wikitext": "{{人物信息\n|image = Cover.jpg\n|简介 = 一句话介绍。\n}}",
        }
        fields = conn.normalize(raw)
        assert fields["image_url"] == "Cover.jpg"
        assert fields["content"] == "一句话介绍。"


# ---------------------------------------------------------------- manifest / discover

class TestManifest:
    def test_discover_registers_moegirl(self):
        names = None
        from app.connectors import registry
        try:
            names = registry.discover()
            conn = registry.get_connector("moegirl")
            assert "moegirl" in names
            assert conn is not None
            assert conn.manifest.display_name == "萌娘百科"
            assert conn.manifest.base_url == "https://zh.moegirl.org.cn/api.php"
            assert "search" in conn.manifest.capabilities
            assert "get_detail" in conn.manifest.capabilities
        finally:
            registry.unregister("moegirl")
