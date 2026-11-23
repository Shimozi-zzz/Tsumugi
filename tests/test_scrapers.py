from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core import scraper_settings as scraper_settings_mod
from backend.core.scraper_settings import (
    load_scraper_settings,
    mask_scraper_settings_for_client,
    save_scraper_settings,
)
from backend.db.database import Base, get_db
from backend.db.models import Game, GameMediaPath, PlayRecord
from backend.main import app
from backend.scrapers.bangumi import BangumiScraper
from backend.scrapers.base import (
    BaseScraper,
    ScraperGameDetail,
    ScraperSearchResult,
    normalize_search_text,
)
from backend.scrapers.dlsite import DLsiteScraper
from backend.scrapers.igdb import IGDBScraper
from backend.scrapers.kungal import KungalScraper
from backend.scrapers.manager import (
    ScraperManager,
    is_derivative_title,
    rerank_results,
    score_search_result,
)
from backend.scrapers.steam import SteamScraper
from backend.scrapers.steamgriddb import SteamGridDBScraper
from backend.scrapers.touchgal import TouchGalScraper
from backend.scrapers.vndb import VNDBScraper
from backend.scrapers.ymgal import YMGalScraper


class _FakeScraper(BaseScraper):
    def __init__(
        self,
        source_id: str,
        *,
        results: list[ScraperSearchResult] | None = None,
        details: dict[str, ScraperGameDetail] | None = None,
        delay: float = 0.0,
        error: Exception | None = None,
        requires_api_key: bool = False,
        api_key: str = "",
        direct_prefix: str = "",
    ) -> None:
        super().__init__(api_key=api_key)
        self.source_id = source_id
        self.source_name = source_id.upper()
        self.display_name = source_id.upper()
        self.requires_api_key = requires_api_key
        self._results = results or []
        self._details = details or {}
        self._delay = delay
        self._error = error
        self._direct_prefix = direct_prefix
        self.search_calls = 0
        self.detail_calls = 0

    def parse_direct_id(self, query: str) -> str | None:
        if self._direct_prefix and query.startswith(self._direct_prefix):
            return query[len(self._direct_prefix) :]
        return None

    async def search(self, query: str, limit: int = 8) -> list[ScraperSearchResult]:
        self.search_calls += 1
        if self._delay > 0:
            await asyncio.sleep(self._delay)
        if self._error:
            raise self._error
        return list(self._results[:limit])

    async def get_detail(self, source_id: str) -> ScraperGameDetail | None:
        self.detail_calls += 1
        if self._delay > 0:
            await asyncio.sleep(self._delay)
        if self._error:
            raise self._error
        return self._details.get(source_id)


class DirectIdRegexTestCase(unittest.TestCase):
    """1. 各类链接/编号直查正则解析测试（含 Kungal、YMGal、RJ 号、VNDB、Bangumi、Steam、IGDB）"""

    def setUp(self) -> None:
        self.manager = ScraperManager()

    def test_kungal_direct_id_parsing(self) -> None:
        scraper = KungalScraper()
        self.assertTrue(scraper.supports_direct_id("https://www.kungal.com/galgame/12345"))
        self.assertEqual(scraper.parse_direct_id("https://www.kungal.com/galgame/12345"), "12345")
        self.assertEqual(scraper.parse_direct_id("https://kungal.org/zh-cn/galgame/9988"), "9988")
        self.assertEqual(scraper.parse_direct_id("kungal:67890"), "67890")
        self.assertEqual(self.manager.detect_direct_id("https://kungal.com/galgame/12345"), ("kungal", "12345"))

        # 自定义域名支持
        custom = KungalScraper(base_url="https://gal.example.org")
        self.assertEqual(custom.parse_direct_id("https://gal.example.org/galgame/42"), "42")

    def test_ymgal_direct_id_parsing(self) -> None:
        scraper = YMGalScraper()
        self.assertTrue(scraper.supports_direct_id("https://www.ymgal.games/GA12345"))
        self.assertEqual(scraper.parse_direct_id("https://www.ymgal.games/GA12345"), "GA12345")
        self.assertEqual(scraper.parse_direct_id("https://ymgal.games/ga9021"), "GA9021")
        self.assertEqual(scraper.parse_direct_id("GA12345"), "GA12345")
        self.assertEqual(scraper.parse_direct_id("ga777"), "GA777")
        self.assertEqual(self.manager.detect_direct_id("https://ymgal.games/GA12345"), ("ymgal", "GA12345"))
        self.assertEqual(self.manager.detect_direct_id("GA54321"), ("ymgal", "GA54321"))

    def test_dlsite_direct_id_parsing(self) -> None:
        scraper = DLsiteScraper()
        self.assertEqual(scraper.parse_direct_id("RJ123456"), "RJ123456")
        self.assertEqual(scraper.parse_direct_id("rj01014447"), "RJ01014447")
        self.assertEqual(scraper.parse_direct_id("VJ01000123"), "VJ01000123")
        self.assertEqual(scraper.parse_direct_id("bj654321"), "BJ654321")
        self.assertEqual(
            scraper.parse_direct_id("https://www.dlsite.com/maniax/work/=/product_id/RJ01014447.html"),
            "RJ01014447",
        )
        self.assertEqual(
            scraper.parse_direct_id("https://www.dlsite.com/pro/work/=/product_id/VJ01000123.html"),
            "VJ01000123",
        )
        self.assertEqual(self.manager.detect_direct_id("RJ123456"), ("dlsite", "RJ123456"))
        self.assertEqual(self.manager.detect_direct_id("VJ123456"), ("dlsite", "VJ123456"))

    def test_vndb_bangumi_steam_igdb_sgdb_direct_id_parsing(self) -> None:
        self.assertEqual(VNDBScraper().parse_direct_id("v12345"), "v12345")
        self.assertEqual(VNDBScraper().parse_direct_id("V17"), "v17")
        self.assertEqual(VNDBScraper().parse_direct_id("https://vndb.org/v20424"), "v20424")
        self.assertEqual(self.manager.detect_direct_id("v12345"), ("vndb", "v12345"))

        self.assertEqual(BangumiScraper().parse_direct_id("https://bgm.tv/subject/12345"), "12345")
        self.assertEqual(BangumiScraper().parse_direct_id("https://bangumi.tv/subject/200763"), "200763")
        self.assertEqual(BangumiScraper().parse_direct_id("bgm:1195"), "1195")
        self.assertEqual(self.manager.detect_direct_id("https://bgm.tv/subject/12345"), ("bangumi", "12345"))

        self.assertEqual(
            SteamScraper().parse_direct_id("https://store.steampowered.com/app/897220/Summer_Pockets/"),
            "897220",
        )
        self.assertEqual(SteamScraper().parse_direct_id("steam://run/1245620"), "1245620")
        self.assertEqual(SteamScraper().parse_direct_id("897220"), "897220")
        self.assertEqual(self.manager.detect_direct_id("https://store.steampowered.com/app/897220"), ("steam", "897220"))
        self.assertEqual(self.manager.detect_direct_id("897220"), ("steam", "897220"))

        self.assertEqual(IGDBScraper().parse_direct_id("https://www.igdb.com/games/elden-ring"), "slug:elden-ring")
        self.assertEqual(IGDBScraper().parse_direct_id("igdb:119133"), "119133")
        self.assertEqual(SteamGridDBScraper().parse_direct_id("https://www.steamgriddb.com/game/5258009"), "5258009")

        self.assertEqual(TouchGalScraper().parse_direct_id("https://www.touchgal.io/galgame/abc12345"), "abc12345")
        self.assertEqual(TouchGalScraper().parse_direct_id("https://www.touchgal.top/xyz98765"), "xyz98765")
        self.assertEqual(TouchGalScraper().parse_direct_id("touchgal:abcd1234"), "abcd1234")
        self.assertIsNone(TouchGalScraper().parse_direct_id("https://www.touchgal.io/search"))
        self.assertEqual(
            self.manager.detect_direct_id("https://www.touchgal.io/galgame/abc12345"),
            ("touchgal", "abc12345"),
        )

    def test_normal_keywords_not_misidentified_as_direct_id(self) -> None:
        for q in ("Summer Pockets", "千恋*万花", "命运石之门", "CLANNAD", "Elden Ring", "Fate/stay night"):
            self.assertIsNone(self.manager.detect_direct_id(q), f"Unexpected direct id match for {q!r}")


class RelevanceRerankingTestCase(unittest.TestCase):
    """2. 归一化相关性打分与衍生条目（OST/设定集/Artbook/Drama CD/体验版）降权重排测试"""

    def test_text_normalization_fullwidth_case_punctuation_variants(self) -> None:
        self.assertEqual(normalize_search_text("Ｓｕｍｍｅｒ　Ｐｏｃｋｅｔｓ"), normalize_search_text("summer pockets"))
        self.assertEqual(normalize_search_text("千恋＊万花"), normalize_search_text("千恋*万花"))
        self.assertEqual(normalize_search_text("天ノ少女"), normalize_search_text("天之少女"))
        self.assertEqual(normalize_search_text("Fate/stay night [Realta Nua]"), normalize_search_text("fatestaynightrealtanua"))

    def test_match_tier_ordering_exact_gt_prefix_gt_substring_gt_fuzzy(self) -> None:
        query = "Summer Pockets"
        exact_title = ScraperSearchResult(source="ymgal", source_id="GA1", title="Summer Pockets")
        exact_alias = ScraperSearchResult(
            source="vndb", source_id="v2", title="夏日口袋", aliases=["Ｓｕｍｍｅｒ　Ｐｏｃｋｅｔｓ"]
        )
        prefix_item = ScraperSearchResult(
            source="bangumi", source_id="3", title="Summer Pockets REFLECTION BLUE"
        )
        substring_item = ScraperSearchResult(
            source="steam", source_id="4", title="The Complete Summer Pockets Anthology Edition"
        )
        fuzzy_item = ScraperSearchResult(source="steam", source_id="5", title="Winter Jacket")

        ranked = rerank_results(
            query,
            [fuzzy_item, substring_item, prefix_item, exact_alias, exact_title],
            category="all",
        )
        ordered_ids = [r.source_id for r in ranked]
        self.assertEqual(ordered_ids, ["GA1", "v2", "3", "4", "5"])
        self.assertGreater(ranked[0].match_score, ranked[1].match_score)
        self.assertGreater(ranked[1].match_score, ranked[2].match_score)
        self.assertGreater(ranked[2].match_score, ranked[3].match_score)
        self.assertGreater(ranked[3].match_score, ranked[4].match_score)

    def test_derivative_items_demoted_unless_explicitly_searched(self) -> None:
        query = "Summer Pockets"
        main_game = ScraperSearchResult(source="vndb", source_id="v20424", title="Summer Pockets")
        edition_game = ScraperSearchResult(
            source="ymgal", source_id="GA2", title="Summer Pockets REFLECTION BLUE"
        )
        ost_item = ScraperSearchResult(
            source="bangumi", source_id="b1", title="Summer Pockets Original Soundtrack"
        )
        ost_short = ScraperSearchResult(
            source="steam", source_id="s1", title="Summer Pockets OST"
        )
        artbook_item = ScraperSearchResult(
            source="bangumi", source_id="b2", title="Summer Pockets 设定集"
        )
        artbook_en = ScraperSearchResult(
            source="steam", source_id="s2", title="Summer Pockets Digital Artbook"
        )
        drama_cd = ScraperSearchResult(
            source="bangumi", source_id="b3", title="Summer Pockets Drama CD"
        )
        demo_item = ScraperSearchResult(
            source="dlsite", source_id="RJ1", title="Summer Pockets 体验版"
        )

        ranked = rerank_results(
            query,
            [ost_item, artbook_item, drama_cd, demo_item, ost_short, artbook_en, edition_game, main_game],
        )
        # 两个主游戏条目必须排在全部衍生品之上
        self.assertEqual(ranked[0].source_id, "v20424")
        self.assertEqual(ranked[1].source_id, "GA2")
        for deriv in ranked[2:]:
            self.assertLess(deriv.match_score, ranked[1].match_score - 15.0)

        # 若用户明确搜索 OST / 设定集，则不降权
        ost_query_score = score_search_result("Summer Pockets Original Soundtrack", ost_item)
        self.assertGreaterEqual(ost_query_score, 90.0)
        artbook_query_score = score_search_result("Summer Pockets 设定集", artbook_item)
        self.assertGreaterEqual(artbook_query_score, 90.0)

    def test_normal_words_containing_ost_or_demo_not_penalized(self) -> None:
        self.assertFalse(is_derivative_title("Ghost of Tsushima"))
        self.assertFalse(is_derivative_title("Demon's Souls"))
        self.assertFalse(is_derivative_title("Lost Judgment"))
        self.assertTrue(is_derivative_title("Elden Ring OST"))
        self.assertTrue(is_derivative_title("CLANNAD 设定资料集"))
        self.assertTrue(is_derivative_title("千恋*万花 体验版"))


class FaultToleranceAndManagerTestCase(unittest.IsolatedAsyncioTestCase):
    """3. 单源超时/异常/未配置 Key 隔离与直查优先级测试"""

    async def test_single_source_timeout_error_and_unconfigured_key_isolation(self) -> None:
        slow_scraper = _FakeScraper("kungal", delay=1.0)
        broken_scraper = _FakeScraper("ymgal", error=RuntimeError("HTTP 403 Cloudflare"))
        unconfigured_key_scraper = _FakeScraper("igdb", requires_api_key=True, api_key="")
        healthy_vndb = _FakeScraper(
            "vndb",
            results=[
                ScraperSearchResult(
                    source="vndb",
                    source_id="v20424",
                    title="Summer Pockets",
                    original_title="サマーポケッツ",
                    developers=["Key"],
                    release_date="2018-06-29",
                    cover_url="https://t.vndb.org/cv/1.jpg",
                )
            ],
        )
        healthy_bgm = _FakeScraper(
            "bangumi",
            results=[
                ScraperSearchResult(
                    source="bangumi",
                    source_id="200763",
                    title="Summer Pockets",
                    description="鸟白岛的夏日物语",
                )
            ],
        )

        manager = ScraperManager(
            per_source_timeout=0.12,
            scrapers_override={
                "kungal": slow_scraper,
                "ymgal": broken_scraper,
                "igdb": unconfigured_key_scraper,
                "vndb": healthy_vndb,
                "bangumi": healthy_bgm,
            },
        )

        res = await manager.search("Summer Pockets", category="all", limit=10)
        # 正常源结果必须完好返回
        returned_sources = {it.source for it in res["items"]}
        self.assertEqual(returned_sources, {"vndb", "bangumi"})
        # 异常与超时源被隔离记录在 source_errors 中
        self.assertIn("kungal", res["source_errors"])
        self.assertIn("超时", res["source_errors"]["kungal"])
        self.assertIn("ymgal", res["source_errors"])
        self.assertIn("403", res["source_errors"]["ymgal"])
        # 未配置 Key 的源被静默跳过，未发起请求也未报错
        self.assertEqual(unconfigured_key_scraper.search_calls, 0)
        self.assertNotIn("igdb", res["source_errors"])

    async def test_direct_id_hits_pinned_source_directly(self) -> None:
        rj_detail = ScraperGameDetail(
            source="dlsite",
            source_id="RJ01014447",
            title="魔法少女的同人视觉小说",
            developers=["示例社团"],
            release_date="2024-05-01",
            external_ids={"dlsite": "RJ01014447"},
        )
        dlsite_fake = _FakeScraper("dlsite", details={"RJ01014447": rj_detail}, direct_prefix="")
        dlsite_fake.parse_direct_id = DLsiteScraper().parse_direct_id  # type: ignore[method-assign]
        other_fake = _FakeScraper("vndb", results=[ScraperSearchResult(source="vndb", source_id="v1", title="Other")])

        manager = ScraperManager(
            scrapers_override={
                "dlsite": dlsite_fake,
                "vndb": other_fake,
            }
        )

        res = await manager.search("RJ01014447", category="all")
        self.assertEqual(len(res["items"]), 1)
        self.assertTrue(res["items"][0].direct_hit)
        self.assertEqual(res["items"][0].match_score, 100.0)
        self.assertEqual(res["items"][0].source_id, "RJ01014447")
        self.assertEqual(res["direct_match"], {"source": "dlsite", "source_id": "RJ01014447"})
        self.assertEqual(dlsite_fake.detail_calls, 1)
        self.assertEqual(other_fake.search_calls, 0)

    def test_concrete_parsers_extract_standardized_fields(self) -> None:
        # Kungal 多语言解析
        kun = KungalScraper()._parse_entry(
            {
                "gid": 10086,
                "name": {"zh-cn": "千恋*万花", "ja-jp": "千恋＊万花", "en-us": "Senren * Banka"},
                "alias": ["千恋万花"],
                "developer": "Yuzusoft",
                "release_date": "2016-07-29",
                "introduction": {"zh-cn": "<p>穗织小镇的恋爱物语</p>"},
                "banner": "/img/banner.jpg",
                "vndb_id": "v19073",
            },
            as_detail=True,
        )
        self.assertEqual(kun.source, "kungal")
        self.assertEqual(kun.source_id, "10086")
        self.assertEqual(kun.title, "千恋*万花")
        self.assertEqual(kun.original_title, "千恋＊万花")
        self.assertIn("Senren * Banka", kun.aliases)
        self.assertEqual(kun.external_ids.get("vndb"), "v19073")
        self.assertEqual(kun.cover_url, "https://www.kungal.com/img/banner.jpg")

        # YMGal 详情解析
        ym = YMGalScraper()._parse_archive_detail(
            {
                "game": {
                    "gid": 2255,
                    "name": "サマーポケッツ",
                    "chineseName": "夏日口袋",
                    "extensionName": [{"name": "Summer Pockets"}],
                    "developerId": 99,
                    "releaseDate": "2018-06-29",
                    "introduction": "在鸟白岛度过的暑假。",
                    "mainImg": "https://cdn.ymgal.games/cover.jpg",
                    "websites": [{"link": "https://vndb.org/v20424"}],
                },
                "oidMapping": {"99": {"chineseName": "Key"}},
            },
            "2255",
        )
        assert ym is not None
        self.assertEqual(ym.source_id, "GA2255")
        self.assertEqual(ym.title, "夏日口袋")
        self.assertEqual(ym.original_title, "サマーポケッツ")
        self.assertEqual(ym.developers, ["Key"])
        self.assertIn("Summer Pockets", ym.aliases)
        self.assertEqual(ym.external_ids.get("vndb"), "v20424")

        # DLsite Product JSON 解析
        dl = DLsiteScraper()._parse_product_json(
            {
                "workno": "RJ01014447",
                "work_name": "星之梦同人篇",
                "maker_name": "星尘社团",
                "regist_date": "2024-02-14 00:00:00",
                "intro_s": "一段短篇视觉小说。",
                "genres": [{"name": "视觉小说"}, {"name": "纯爱"}],
                "image_main": {"url": "//img.dlsite.jp/main.jpg"},
                "age_category": 1,
            },
            "RJ01014447",
            "home",
        )
        self.assertEqual(dl.source_id, "RJ01014447")
        self.assertEqual(dl.developers, ["星尘社团"])
        self.assertEqual(dl.release_date, "2024-02-14")
        self.assertEqual(dl.cover_url, "https://img.dlsite.jp/main.jpg")
        self.assertFalse(dl.is_nsfw)

        # VNDB extlinks 同时提取 Steam 与 DLsite
        vn = VNDBScraper()._parse_vn_entry(
            {
                "id": "v20424",
                "title": "Summer Pockets",
                "alttitle": "サマーポケッツ",
                "titles": [{"lang": "zh-hans", "title": "夏日口袋"}],
                "aliases": ["SP"],
                "released": "2018-06-29",
                "developers": [{"original": "Key"}],
                "extlinks": [
                    {"name": "steam", "id": "897220", "url": "https://store.steampowered.com/app/897220"},
                    {"name": "dlsite", "id": "VJ013456", "url": "https://www.dlsite.com/pro/work/=/product_id/VJ013456.html"},
                ],
            },
            as_detail=True,
        )
        self.assertEqual(vn.external_ids.get("steam"), "897220")
        self.assertEqual(vn.external_ids.get("dlsite"), "VJ013456")
        self.assertIn("SP", vn.aliases)

        # IGDB 详情解析
        ig = IGDBScraper(client_id="cid", client_secret="csec")._parse_game(
            {
                "id": 119133,
                "name": "Elden Ring",
                "slug": "elden-ring",
                "alternative_names": [{"name": "艾尔登法环"}],
                "first_release_date": 1645747200,
                "cover": {"image_id": "co4jni"},
                "artworks": [{"image_id": "ar1234"}],
                "involved_companies": [
                    {"company": {"name": "FromSoftware"}, "developer": True, "publisher": False},
                    {"company": {"name": "Bandai Namco"}, "developer": False, "publisher": True},
                ],
                "websites": [{"url": "https://store.steampowered.com/app/1245620"}],
                "total_rating": 95.4,
            },
            as_detail=True,
        )
        self.assertEqual(ig.developers, ["FromSoftware"])
        self.assertEqual(ig.publishers, ["Bandai Namco"])
        self.assertEqual(ig.release_date, "2022-02-25")
        self.assertIn("艾尔登法环", ig.aliases)
        self.assertEqual(ig.external_ids.get("steam"), "1245620")

    async def test_category_presets_and_cross_source_enrichment(self) -> None:
        ymgal_detail = ScraperGameDetail(
            source="ymgal",
            source_id="GA2255",
            title="夏日口袋",
            original_title="サマーポケッツ",
            description="在鸟白岛与少女们共同编织的夏日回忆。",
            developers=["Key"],
            release_date="2018-06-29",
            tags=["催泪", "日常"],
            cover_url="https://cdn.ymgal.games/cover.jpg",
            external_ids={"ymgal": "GA2255", "vndb": "v20424"},
        )
        ymgal_fake = _FakeScraper(
            "ymgal",
            results=[ymgal_detail],
            details={"GA2255": ymgal_detail},
        )
        steam_fake = _FakeScraper("steam", results=[])
        igdb_unconfigured = _FakeScraper("igdb", requires_api_key=True, api_key="")
        igdb_configured = _FakeScraper("igdb", requires_api_key=True, api_key="secret")

        mgr_no_key = ScraperManager(
            scraper_settings={"enabled_sources": {"dlsite": False}},
            scrapers_override={
                "ymgal": ymgal_fake,
                "kungal": _FakeScraper("kungal"),
                "vndb": _FakeScraper("vndb"),
                "bangumi": _FakeScraper("bangumi"),
                "dlsite": _FakeScraper("dlsite"),
                "steam": steam_fake,
                "igdb": igdb_unconfigured,
            },
        )
        self.assertEqual(
            mgr_no_key.resolve_target_sources(category="galgame"),
            ["ymgal", "kungal", "vndb", "bangumi"],  # dlsite 已禁用
        )
        self.assertEqual(
            mgr_no_key.resolve_target_sources(category="general"),
            ["steam", "bangumi"],  # igdb 未配 Key 自动跳过
        )

        mgr_with_igdb = ScraperManager(
            scrapers_override={
                "ymgal": ymgal_fake,
                "steam": steam_fake,
                "bangumi": _FakeScraper("bangumi"),
                "igdb": igdb_configured,
            }
        )
        self.assertEqual(
            mgr_with_igdb.resolve_target_sources(category="general"),
            ["steam", "igdb", "bangumi"],
        )

        # 验证 TouchGal 未配 Key 时不参与「综合推荐」，配置 Key 后自动参与「综合推荐」
        mgr_tgal_no_key = ScraperManager(scraper_settings={"touchgal_api_key": ""})
        self.assertNotIn("touchgal", mgr_tgal_no_key.resolve_target_sources(category="all"))
        self.assertIn("touchgal", mgr_tgal_no_key.resolve_target_sources(sources=["touchgal"]))

        mgr_tgal_with_key = ScraperManager(scraper_settings={"touchgal_api_key": "tgal_secret_key"})
        self.assertIn("touchgal", mgr_tgal_with_key.resolve_target_sources(category="all"))
        self.assertIn("touchgal", mgr_tgal_with_key.resolve_target_sources(category="galgame"))

        # 验证跨源补全：主条目来自 VNDB（缺中文简介），自动从 YMGal 补全中文简介与封面并收敛外部 ID
        enriched = await mgr_no_key.enrich(
            title="Summer Pockets",
            original_title="サマーポケッツ",
            release_date="2018-06-29",
            source="vndb",
            source_id="v20424",
            external_ids={"vndb": "v20424"},
            mode="all",
        )
        self.assertEqual(len(enriched["descriptions"]), 1)
        self.assertEqual(enriched["descriptions"][0]["source"], "ymgal")
        self.assertTrue(enriched["descriptions"][0]["has_chinese"])
        self.assertIn("鸟白岛", enriched["descriptions"][0]["description"])
        self.assertEqual(len(enriched["covers"]), 1)
        self.assertEqual(enriched["merged_external_ids"].get("ymgal"), "GA2255")
        self.assertEqual(enriched["merged_external_ids"].get("vndb"), "v20424")


class ScraperSettingsAndApiTestCase(unittest.IsolatedAsyncioTestCase):
    """4. 本地 settings.json 持久化、密钥脱敏与 API 路由端到端验证"""

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="tsumugi_scraper_test_")
        self.tmp_dir = Path(self._tmp.name)
        self.settings_json = self.tmp_dir / "settings.json"
        self.db_path = self.tmp_dir / "test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path.as_posix()}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_maker = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self._patch_settings = patch.object(scraper_settings_mod, "SETTINGS_JSON_PATH", self.settings_json)
        self._patch_settings.start()

    async def asyncTearDown(self) -> None:
        self._patch_settings.stop()
        await self.engine.dispose()
        self._tmp.cleanup()

    def test_settings_json_persistence_and_secret_masking(self) -> None:
        saved = save_scraper_settings(
            {
                "enabled_sources": {"dlsite": False, "ymgal": True},
                "ymgal_client_id": "my_ym_id",
                "ymgal_client_secret": "super_secret_ymgal_token",
                "kungal_base_url": "https://kungal.custom.org/",
                "kungal_token": "kun_secret_987654",
                "bangumi_token": "bgm_secret_abcdef",
                "steamgriddb_api_key": "sgdb_1234567890",
                "igdb_client_id": "twitch_id_1",
                "igdb_client_secret": "twitch_secret_xyz987",
            },
            path=self.settings_json,
        )
        self.assertTrue(self.settings_json.is_file())
        self.assertFalse(saved["enabled_sources"]["dlsite"])
        self.assertEqual(saved["kungal_base_url"], "https://kungal.custom.org")

        # 脱敏检查：绝不泄露明文密钥
        masked = mask_scraper_settings_for_client(saved)
        self.assertNotIn("super_secret_ymgal_token", masked["ymgal_client_secret"])
        self.assertNotIn("sgdb_1234567890", masked["steamgriddb_api_key"])
        self.assertNotIn("twitch_secret_xyz987", masked["igdb_client_secret"])
        self.assertTrue(masked["configured_secrets"]["steamgriddb_api_key"])
        self.assertTrue(masked["source_status"]["igdb"]["configured"])

        # 再次提交掩码占位符时，不得覆盖原有真实密钥
        resaved = save_scraper_settings(
            {
                "steamgriddb_api_key": masked["steamgriddb_api_key"],
                "bangumi_token": masked["bangumi_token"],
            },
            path=self.settings_json,
        )
        self.assertEqual(resaved["steamgriddb_api_key"], "sgdb_1234567890")
        self.assertEqual(resaved["bangumi_token"], "bgm_secret_abcdef")

        # 显式 clear_fields 可清空对应密钥
        cleared = save_scraper_settings({"clear_fields": ["steamgriddb_api_key"]}, path=self.settings_json)
        self.assertEqual(cleared["steamgriddb_api_key"], "")
        loaded = load_scraper_settings(path=self.settings_json)
        self.assertEqual(loaded["steamgriddb_api_key"], "")

    async def test_api_scraper_settings_and_library_duplicate_annotation(self) -> None:
        # 预先写入一款在库游戏（VNDB v20424）
        async with self.session_maker() as db:
            g = Game(
                title="Summer Pockets",
                sub_title="サマーポケッツ",
                external_ids={"vndb": "v20424"},
                bangumi_id="200763",
            )
            g.media = GameMediaPath()
            g.play_record = PlayRecord(total_seconds=0)
            db.add(g)
            await db.commit()
            existing_id = g.id

        async def _override_get_db():
            async with self.session_maker() as session:
                yield session

        app.dependency_overrides[get_db] = _override_get_db
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                # 1. 保存刮削源设置并验证脱敏响应（含 TouchGal / SteamGridDB / IGDB）
                r_put = await client.put(
                    "/api/system/scraper-settings",
                    json={
                        "enabled_sources": {"kungal": True, "ymgal": True, "touchgal": True},
                        "touchgal_api_key": "tgal_live_secret_7777",
                        "steamgriddb_api_key": "sgdb_live_secret_9999",
                        "igdb_client_id": "tw_client_id",
                        "igdb_client_secret": "tw_client_secret_8888",
                    },
                )
                self.assertEqual(r_put.status_code, 200)
                body = r_put.json()
                self.assertNotEqual(body["touchgal_api_key"], "tgal_live_secret_7777")
                self.assertNotEqual(body["steamgriddb_api_key"], "sgdb_live_secret_9999")
                self.assertTrue(body["configured_secrets"]["touchgal_api_key"])
                self.assertTrue(body["configured_secrets"]["steamgriddb_api_key"])
                self.assertTrue(body["source_status"]["touchgal"]["configured"])
                self.assertTrue(body["source_status"]["igdb"]["configured"])

                # 2. /api/scraper/sources 应报告 TouchGal、SGDB 与 IGDB 均已解锁
                r_src = await client.get("/api/scraper/sources")
                self.assertEqual(r_src.status_code, 200)
                self.assertTrue(r_src.json()["touchgal_configured"])
                self.assertTrue(r_src.json()["sgdb_configured"])
                self.assertTrue(r_src.json()["igdb_configured"])

                # 3. 模拟 /api/scraper/search 不传 category 时默认综合推荐全源检索并标注 already_in_library
                fake_item = ScraperSearchResult(
                    source="vndb",
                    source_id="v20424",
                    title="Summer Pockets",
                    original_title="サマーポケッツ",
                    external_ids={"vndb": "v20424"},
                    match_score=96.0,
                )
                with patch.object(
                    ScraperManager,
                    "search",
                    return_value={
                        "query": "Summer Pockets",
                        "category": "all",
                        "sources": ["ymgal", "kungal", "vndb", "bangumi", "dlsite", "steam"],
                        "direct_match": None,
                        "items": [fake_item],
                        "source_errors": {},
                    },
                ):
                    r_search = await client.get(
                        "/api/scraper/search",
                        params={"q": "Summer Pockets"},
                    )
                    self.assertEqual(r_search.status_code, 200)
                    sdata = r_search.json()
                    self.assertEqual(sdata["category"], "all")
                    self.assertEqual(sdata["count"], 1)
                    self.assertTrue(sdata["items"][0]["already_in_library"])
                    self.assertEqual(sdata["items"][0]["existing_game_id"], existing_id)

                # 4. 校验 /api/import/external/{source}/detect 返回 HTTP 200 及中性空路径结构
                for ext_src in ("playnite", "vnite"):
                    r_det = await client.get(f"/api/import/external/{ext_src}/detect")
                    self.assertEqual(r_det.status_code, 200)
                    dbody = r_det.json()
                    self.assertIn("found", dbody)
                    self.assertIn("path", dbody)
                    self.assertIn("message", dbody)
                    if not dbody["found"]:
                        self.assertEqual(dbody["path"], "")
                        self.assertEqual(dbody["message"], "未自动检测到默认路径，请手动输入路径或选择目录")

                # 5. 校验全部 9 个数据源测试接口 POST /api/scraper/test/{source} 绝不返回 405
                all_sources = (
                    "touchgal",
                    "ymgal",
                    "kungal",
                    "vndb",
                    "bangumi",
                    "dlsite",
                    "steam",
                    "steamgriddb",
                    "igdb",
                )

                async def _mock_test_source(self_mgr, src: str, timeout: float = 6.0):
                    return {
                        "ok": True,
                        "source": src,
                        "latency_ms": 42,
                        "detail": "连接正常 (42ms)",
                    }

                with patch.object(ScraperManager, "test_source", new=_mock_test_source):
                    for sid in all_sources:
                        r_test = await client.post(f"/api/scraper/test/{sid}", json={})
                        self.assertNotEqual(r_test.status_code, 405, f"Unexpected 405 on {sid}")
                        self.assertEqual(r_test.status_code, 200, f"Unexpected status on {sid}: {r_test.text}")
                        tbody = r_test.json()
                        self.assertEqual(tbody["source"], sid)
                        self.assertTrue(tbody["ok"])

                # 6. 校验未匹配的 /api/* 任意 HTTP 方法请求返回 404 而非 405
                for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                    r_missing = await client.request(method, "/api/__nonexistent__")
                    self.assertEqual(
                        r_missing.status_code,
                        404,
                        f"{method} /api/__nonexistent__ returned {r_missing.status_code}",
                    )
        finally:
            app.dependency_overrides.pop(get_db, None)

    async def test_connectivity_probes_missing_key_and_timeout_handling(self) -> None:
        # 未配置 API Key 时直接返回明确中文失败原因（不发外网请求）
        for scraper in (
            TouchGalScraper(api_key=""),
            SteamGridDBScraper(api_key=""),
            IGDBScraper(client_id="", client_secret=""),
        ):
            res = await scraper.test_connection(timeout=6.0)
            self.assertFalse(res["ok"])
            self.assertIn("未配置", res["detail"])

        # 超时场景（模拟 httpx.TimeoutException）必须返回 ok=False 与超时提示，绝不误报成功
        async def _raise_timeout(*_args, **_kwargs):
            raise httpx.ReadTimeout("timed out")

        with patch.object(httpx.AsyncClient, "post", side_effect=_raise_timeout):
            res_vndb = await VNDBScraper().test_connection(timeout=6.0)
            self.assertFalse(res_vndb["ok"])
            self.assertIn("超时", res_vndb["detail"])

            res_tgal = await TouchGalScraper(api_key="demo_key").test_connection(timeout=6.0)
            self.assertFalse(res_tgal["ok"])
            self.assertIn("超时", res_tgal["detail"])


if __name__ == "__main__":
    unittest.main()
