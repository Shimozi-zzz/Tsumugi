from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core import scraper_settings as scraper_settings_mod
from backend.db.database import Base, get_db
from backend.db.models import Game, GameMediaPath, PlayRecord
from backend.main import app
from backend.scrapers import asset_search as asset_search_mod
from backend.scrapers.asset_search import (
    AssetCandidate,
    _canonicalize_asset_url,
    search_asset_candidates,
)
from backend.scrapers.base import ScraperSearchResult


def _cand(
    source: str,
    url: str,
    title: str = "Summer Pockets",
    *,
    width: int | None = None,
    height: int | None = None,
    thumb_url: str | None = None,
) -> AssetCandidate:
    return AssetCandidate(
        id=asset_search_mod._make_id(source, url),
        url=url,
        thumb_url=thumb_url or url,
        source=source,
        title=title,
        width=width,
        height=height,
        mime_hint="image",
    )


class HeroAssetSearchAggregationTestCase(unittest.IsolatedAsyncioTestCase):
    """验证宽幅 Hero 在线查图并发并入封面源、去重角色标记、排序、异常隔离与 Cover 不受影响"""

    async def test_hero_search_merges_hero_and_cover_sources_with_order_and_orientation_sort(self) -> None:
        calls: list[tuple[str, str]] = []

        async def _fake_sgdb(asset_type, query, scraper, steam_appid=""):
            calls.append(("steamgriddb", asset_type))
            await asyncio.sleep(0.05)
            if asset_type == "hero":
                return [_cand("SteamGridDB", "https://cdn.sgdb.com/hero_1.png", width=1920, height=620)], []
            return [_cand("SteamGridDB", "https://cdn.sgdb.com/grid_1.png", width=600, height=900)], []

        async def _fake_vndb(asset_type, query, scraper):
            calls.append(("vndb", asset_type))
            if asset_type == "hero":
                return [_cand("VNDB", "https://t.vndb.org/sf/ss_1.jpg", width=1280, height=720)]
            return [
                _cand("VNDB", "https://t.vndb.org/cv/portrait.jpg", width=400, height=600),
                _cand("VNDB", "https://t.vndb.org/cv/landscape.jpg", width=1200, height=800),
            ]

        async def _fake_steam(asset_type, query, scraper):
            calls.append(("steam", asset_type))
            if asset_type == "hero":
                return [_cand("Steam", "https://shared.akamai.steamstatic.com/app/1/library_hero.jpg")]
            return [
                _cand("Steam", "https://shared.akamai.steamstatic.com/app/1/library_600x900_2x.jpg", width=600, height=900),
                _cand("Steam", "https://shared.akamai.steamstatic.com/app/1/header.jpg", width=460, height=215),
            ]

        async def _fake_bgm(asset_type, query, scraper):
            calls.append(("bangumi", asset_type))
            if asset_type == "cover":
                await asyncio.sleep(0.05)
                return [_cand("Bangumi", "https://lain.bgm.tv/pic/cover/l/bgm_1.jpg")]
            return []

        async def _fake_tgal(asset_type, query, scraper):
            calls.append(("touchgal", asset_type))
            if asset_type == "cover":
                return [_cand("TouchGal", "https://cdn.touchgal.io/banner_1.jpg")]
            return []

        async def _fake_generic(asset_type, query, scraper, source_label):
            calls.append((source_label.lower(), asset_type))
            if source_label == "Kungal":
                if asset_type == "hero":
                    return [_cand("Kungal", "https://www.kungal.com/img/hero_banner.jpg")]
                return [_cand("Kungal", "https://www.kungal.com/img/cover_only.jpg")]
            if source_label == "IGDB":
                if asset_type == "hero":
                    return [_cand("IGDB", "https://images.igdb.com/t_1080p/art1.jpg")]
                return [_cand("IGDB", "https://images.igdb.com/t_cover_big_2x/cov1.jpg")]
            if source_label == "YMGal":
                return [_cand("YMGal", "https://cdn.ymgal.games/main_1.jpg")]
            if source_label == "DLsite":
                return [_cand("DLsite", "https://img.dlsite.jp/RJ123456_main.jpg")]
            return []

        t0 = time.monotonic()
        with (
            patch.object(asset_search_mod, "_fetch_sgdb_candidates", side_effect=_fake_sgdb),
            patch.object(asset_search_mod, "_fetch_vndb_candidates", side_effect=_fake_vndb),
            patch.object(asset_search_mod, "_fetch_steam_candidates", side_effect=_fake_steam),
            patch.object(asset_search_mod, "_fetch_bangumi_candidates", side_effect=_fake_bgm),
            patch.object(asset_search_mod, "_fetch_touchgal_candidates", side_effect=_fake_tgal),
            patch.object(asset_search_mod, "_fetch_generic_scraper_image_candidates", side_effect=_fake_generic),
        ):
            res = await search_asset_candidates(
                "hero",
                "Summer Pockets",
                source="all",
                api_keys={
                    "steamgriddb": "sgdb_key",
                    "touchgal": "tgal_key",
                    "igdb_client_id": "cid",
                    "igdb_client_secret": "csec",
                },
            )
        elapsed = time.monotonic() - t0

        # Hero 源与封面源应并发执行（两个 0.05s 任务总耗时应显著低于串行的 0.10s）
        self.assertLess(elapsed, 0.095)

        items = res["items"]
        roles = [it["asset_role"] for it in items]
        self.assertIn("hero", roles)
        self.assertIn("cover", roles)

        # 原有 Hero 源全部排在前面，且严格保持 SteamGridDB -> VNDB -> Steam -> Kungal -> IGDB 顺序
        hero_items = [it for it in items if it["asset_role"] == "hero"]
        cover_items = [it for it in items if it["asset_role"] == "cover"]
        self.assertEqual(items[: len(hero_items)], hero_items)
        self.assertEqual(items[len(hero_items) :], cover_items)
        self.assertEqual(
            [it["source"] for it in hero_items],
            ["SteamGridDB", "VNDB", "Steam", "Kungal", "IGDB"],
        )

        # 封面源内部排序：已知横图(width >= height) -> 未知尺寸 -> 已知竖图(width < height)
        cover_urls = [it["url"] for it in cover_items]
        landscape_urls = {
            "https://t.vndb.org/cv/landscape.jpg",
            "https://shared.akamai.steamstatic.com/app/1/header.jpg",
        }
        unknown_urls = {
            "https://cdn.touchgal.io/banner_1.jpg",
            "https://cdn.ymgal.games/main_1.jpg",
            "https://www.kungal.com/img/cover_only.jpg",
            "https://lain.bgm.tv/pic/cover/l/bgm_1.jpg",
            "https://img.dlsite.jp/RJ123456_main.jpg",
            "https://images.igdb.com/t_cover_big_2x/cov1.jpg",
        }
        portrait_urls = {
            "https://t.vndb.org/cv/portrait.jpg",
            "https://shared.akamai.steamstatic.com/app/1/library_600x900_2x.jpg",
            "https://cdn.sgdb.com/grid_1.png",
        }

        self.assertEqual(set(cover_urls[:2]), landscape_urls)
        self.assertEqual(set(cover_urls[2:8]), unknown_urls)
        self.assertEqual(set(cover_urls[8:]), portrait_urls)

    async def test_hero_search_url_normalization_dedup_keeps_hero_role(self) -> None:
        # 校验 URL 归一化键
        self.assertEqual(
            _canonicalize_asset_url("http://CDN.Example.COM:80/img/a.jpg?b=2&a=1#frag"),
            _canonicalize_asset_url("https://cdn.example.com:443/img/a.jpg?a=1&b=2"),
        )
        self.assertEqual(
            _canonicalize_asset_url("//img.dlsite.jp/work/main.jpg"),
            _canonicalize_asset_url("https://img.dlsite.jp/work/main.jpg"),
        )
        self.assertNotEqual(
            _canonicalize_asset_url("https://cdn.example.com/img.jpg?id=1"),
            _canonicalize_asset_url("https://cdn.example.com/img.jpg?id=2"),
        )

        async def _fake_sgdb(asset_type, query, scraper, steam_appid=""):
            if asset_type == "hero":
                return [
                    _cand("SteamGridDB", "https://cdn.example.com/shared.jpg", width=1920, height=620),
                    _cand("SteamGridDB", "https://cdn.example.com/variant.jpg?a=1&b=2", width=1920, height=1080),
                ], []
            return [
                # 与 Hero 源完全相同 URL
                _cand("SteamGridDB", "https://cdn.example.com/shared.jpg", width=600, height=900),
                # 仅协议/域名大小写/默认端口/参数顺序/fragment 不同的同一张图
                _cand("SteamGridDB", "http://CDN.EXAMPLE.COM:80/variant.jpg?b=2&a=1#preview", width=600, height=900),
                # 真正不同的封面图
                _cand("SteamGridDB", "https://cdn.example.com/unique_grid.jpg?id=2", width=600, height=900),
            ], []

        async def _empty(*_args, **_kwargs):
            return []

        async def _fake_generic(asset_type, query, scraper, source_label):
            if source_label == "Kungal":
                if asset_type == "hero":
                    return [_cand("Kungal", "https://www.kungal.com/banner.jpg")]
                # 封面源返回同 URL，去重必须保留 Hero 角色
                return [_cand("Kungal", "http://www.kungal.com/banner.jpg/")]
            if source_label == "YMGal":
                return [
                    _cand("YMGal", "https://cdn.example.com/shared.jpg"),
                    _cand("YMGal", "https://cdn.ymgal.games/cover_unique.jpg"),
                ]
            return []

        with (
            patch.object(asset_search_mod, "_fetch_sgdb_candidates", side_effect=_fake_sgdb),
            patch.object(asset_search_mod, "_fetch_vndb_candidates", side_effect=_empty),
            patch.object(asset_search_mod, "_fetch_steam_candidates", side_effect=_empty),
            patch.object(asset_search_mod, "_fetch_bangumi_candidates", side_effect=_empty),
            patch.object(asset_search_mod, "_fetch_touchgal_candidates", side_effect=_empty),
            patch.object(asset_search_mod, "_fetch_generic_scraper_image_candidates", side_effect=_fake_generic),
        ):
            res = await search_asset_candidates(
                "hero",
                "Summer Pockets",
                source="all",
                api_keys={"steamgriddb": "sgdb_key"},
            )

        items = res["items"]
        canon_urls = [_canonicalize_asset_url(it["url"]) for it in items]
        self.assertEqual(len(canon_urls), len(set(canon_urls)), "Returned items must not contain duplicate URLs")

        by_canon = {_canonicalize_asset_url(it["url"]): it for it in items}
        # 同图同时命中 Hero 源与封面源：保留 Hero 排序位置与 asset_role="hero"，同时在 asset_roles 中无损记录双角色
        self.assertEqual(by_canon["https://cdn.example.com/shared.jpg"]["asset_role"], "hero")
        self.assertEqual(by_canon["https://cdn.example.com/shared.jpg"]["asset_roles"], ["hero", "cover"])
        self.assertEqual(by_canon["https://cdn.example.com/shared.jpg"]["source"], "SteamGridDB")
        self.assertEqual(by_canon["https://cdn.example.com/variant.jpg?a=1&b=2"]["asset_role"], "hero")
        self.assertEqual(
            by_canon["https://cdn.example.com/variant.jpg?a=1&b=2"]["asset_roles"],
            ["hero", "cover"],
        )
        self.assertEqual(by_canon["https://www.kungal.com/banner.jpg"]["asset_role"], "hero")
        self.assertEqual(by_canon["https://www.kungal.com/banner.jpg"]["asset_roles"], ["hero", "cover"])
        self.assertEqual(by_canon["https://cdn.ymgal.games/cover_unique.jpg"]["asset_role"], "cover")
        self.assertEqual(by_canon["https://cdn.ymgal.games/cover_unique.jpg"]["asset_roles"], ["cover"])
        self.assertEqual(by_canon["https://cdn.example.com/unique_grid.jpg?id=2"]["asset_role"], "cover")
        self.assertEqual(by_canon["https://cdn.example.com/unique_grid.jpg?id=2"]["asset_roles"], ["cover"])

        # 前端按 asset_roles 过滤「封面源」时，重叠图与纯封面图都必须保留，绝不会出现 封面源 (0)
        cover_role_urls = {_canonicalize_asset_url(it["url"]) for it in items if "cover" in it["asset_roles"]}
        self.assertEqual(
            cover_role_urls,
            {
                "https://cdn.example.com/shared.jpg",
                "https://cdn.example.com/variant.jpg?a=1&b=2",
                "https://www.kungal.com/banner.jpg",
                "https://cdn.ymgal.games/cover_unique.jpg",
                "https://cdn.example.com/unique_grid.jpg?id=2",
            },
        )

    async def test_hero_search_isolates_cover_source_failures_and_timeouts(self) -> None:
        async def _fake_sgdb(asset_type, query, scraper, steam_appid=""):
            if asset_type == "hero":
                return [_cand("SteamGridDB", "https://cdn.sgdb.com/hero_ok.png", width=1920, height=620)], []
            raise RuntimeError("SGDB grid 500 error")

        async def _fake_vndb(asset_type, query, scraper):
            if asset_type == "hero":
                return [_cand("VNDB", "https://t.vndb.org/sf/hero_ss.jpg", width=1280, height=720)]
            # 模拟慢封面源超时
            await asyncio.sleep(0.5)
            return [_cand("VNDB", "https://t.vndb.org/cv/too_slow.jpg")]

        async def _fake_bgm(asset_type, query, scraper):
            raise RuntimeError("Bangumi 502 Bad Gateway")

        async def _fake_tgal(asset_type, query, scraper):
            return [_cand("TouchGal", "https://cdn.touchgal.io/healthy_cover.jpg")]

        async def _empty(*_args, **_kwargs):
            return []

        with (
            patch.object(asset_search_mod, "_fetch_sgdb_candidates", side_effect=_fake_sgdb),
            patch.object(asset_search_mod, "_fetch_vndb_candidates", side_effect=_fake_vndb),
            patch.object(asset_search_mod, "_fetch_steam_candidates", side_effect=_empty),
            patch.object(asset_search_mod, "_fetch_bangumi_candidates", side_effect=_fake_bgm),
            patch.object(asset_search_mod, "_fetch_touchgal_candidates", side_effect=_fake_tgal),
            patch.object(asset_search_mod, "_fetch_generic_scraper_image_candidates", side_effect=_empty),
        ):
            res = await search_asset_candidates(
                "hero",
                "Summer Pockets",
                source="all",
                api_keys={"steamgriddb": "sgdb_key", "touchgal": "tgal_key"},
                per_source_timeout=0.06,
            )

        items = res["items"]
        urls = [it["url"] for it in items]
        self.assertEqual(
            urls,
            [
                "https://cdn.sgdb.com/hero_ok.png",
                "https://t.vndb.org/sf/hero_ss.jpg",
                "https://cdn.touchgal.io/healthy_cover.jpg",
            ],
        )
        self.assertEqual([it["asset_role"] for it in items], ["hero", "hero", "cover"])

    async def test_cover_search_behavior_is_unaffected(self) -> None:
        recorded_calls: list[tuple[str, str]] = []

        async def _fake_sgdb(asset_type, query, scraper, steam_appid=""):
            recorded_calls.append(("steamgriddb", asset_type))
            return [_cand("SteamGridDB", "https://cdn.sgdb.com/grid_600x900.png", width=600, height=900)], []

        async def _fake_vndb(asset_type, query, scraper):
            recorded_calls.append(("vndb", asset_type))
            return [_cand("VNDB", "https://t.vndb.org/cv/vndb_cover.jpg", width=400, height=600)]

        async def _fake_bgm(asset_type, query, scraper):
            recorded_calls.append(("bangumi", asset_type))
            return [_cand("Bangumi", "https://lain.bgm.tv/pic/cover/l/bgm_cover.jpg")]

        async def _fake_steam(asset_type, query, scraper):
            recorded_calls.append(("steam", asset_type))
            return [_cand("Steam", "https://shared.akamai.steamstatic.com/app/1/header.jpg", width=460, height=215)]

        async def _fake_tgal(asset_type, query, scraper):
            recorded_calls.append(("touchgal", asset_type))
            return [_cand("TouchGal", "https://cdn.touchgal.io/should_not_be_called_in_all.jpg")]

        async def _fake_generic(asset_type, query, scraper, source_label):
            recorded_calls.append((source_label.lower(), asset_type))
            return [_cand(source_label, f"https://example.com/{source_label.lower()}_cover.jpg")]

        with (
            patch.object(asset_search_mod, "_fetch_sgdb_candidates", side_effect=_fake_sgdb),
            patch.object(asset_search_mod, "_fetch_vndb_candidates", side_effect=_fake_vndb),
            patch.object(asset_search_mod, "_fetch_steam_candidates", side_effect=_fake_steam),
            patch.object(asset_search_mod, "_fetch_bangumi_candidates", side_effect=_fake_bgm),
            patch.object(asset_search_mod, "_fetch_touchgal_candidates", side_effect=_fake_tgal),
            patch.object(asset_search_mod, "_fetch_generic_scraper_image_candidates", side_effect=_fake_generic),
        ):
            res = await search_asset_candidates(
                "cover",
                "Summer Pockets",
                source="all",
                api_keys={"steamgriddb": "sgdb_key", "touchgal": "tgal_key", "igdb_client_id": "id", "igdb_client_secret": "sec"},
            )

        # Cover 查图与 Hero 封面分支统一使用同一 COVER_DEFAULT_SOURCES 管线（未配置 Key 的扩展源不发请求）
        self.assertEqual(
            recorded_calls,
            [
                ("steamgriddb", "cover"),
                ("ymgal", "cover"),
                ("kungal", "cover"),
                ("touchgal", "cover"),
                ("vndb", "cover"),
                ("bangumi", "cover"),
                ("dlsite", "cover"),
                ("steam", "cover"),
                ("igdb", "cover"),
            ],
        )
        # Cover 查图保持原有顺序（不把 Steam 横版头图重排到 SteamGridDB 竖版 Grid 之前）
        self.assertEqual(
            [it["source"] for it in res["items"]],
            ["SteamGridDB", "YMGal", "Kungal", "TouchGal", "VNDB", "Bangumi", "DLsite", "Steam", "IGDB"],
        )
        self.assertTrue(all(it["asset_role"] == "cover" for it in res["items"]))
        self.assertTrue(all(it["asset_roles"] == ["cover"] for it in res["items"]))

    async def test_hero_reuses_full_cover_pipeline_with_alt_title_fallback(self) -> None:
        """验证封面原图能搜出的每一张图（含 alt_title 回退），在 Hero 查图「封面源」中 100% 出现"""

        async def _fake_sgdb(asset_type, query, scraper, steam_appid=""):
            return [], ["SteamGridDB 未配置"]

        async def _fake_vndb(asset_type, query, scraper):
            if asset_type == "hero" and query == "サマーポケッツ":
                return [_cand("VNDB", "https://t.vndb.org/sf/sp_hero.jpg", width=1280, height=720)]
            if asset_type == "cover" and query == "サマーポケッツ":
                return [_cand("VNDB", "https://t.vndb.org/cv/sp_vndb.jpg", width=400, height=600)]
            return []

        async def _fake_bgm(asset_type, query, scraper):
            # 模拟中文名命中 Bangumi，而主查询词为日文原名时通过 alt_title 回退命中
            if asset_type == "cover" and query == "夏日口袋":
                return [_cand("Bangumi", "https://lain.bgm.tv/pic/cover/l/sp_bgm.jpg")]
            return []

        async def _fake_generic(asset_type, query, scraper, source_label):
            if source_label == "YMGal" and asset_type == "cover" and query == "夏日口袋":
                return [_cand("YMGal", "https://cdn.ymgal.games/sp_ymgal.jpg")]
            if source_label == "Kungal" and query == "サマーポケッツ":
                # 同一 URL 同时作为 Kungal 的 Hero 与 Cover 返回
                return [_cand("Kungal", "https://www.kungal.com/sp_shared.jpg")]
            return []

        async def _empty(*_args, **_kwargs):
            return []

        with (
            patch.object(asset_search_mod, "_fetch_sgdb_candidates", side_effect=_fake_sgdb),
            patch.object(asset_search_mod, "_fetch_vndb_candidates", side_effect=_fake_vndb),
            patch.object(asset_search_mod, "_fetch_steam_candidates", side_effect=_empty),
            patch.object(asset_search_mod, "_fetch_bangumi_candidates", side_effect=_fake_bgm),
            patch.object(asset_search_mod, "_fetch_touchgal_candidates", side_effect=_empty),
            patch.object(asset_search_mod, "_fetch_generic_scraper_image_candidates", side_effect=_fake_generic),
        ):
            cover_res = await search_asset_candidates(
                "cover",
                "サマーポケッツ",
                source="all",
                alt_title="夏日口袋",
                api_keys={},
            )
            hero_res = await search_asset_candidates(
                "hero",
                "サマーポケッツ",
                source="all",
                alt_title="夏日口袋",
                api_keys={},
            )

        cover_urls = {_canonicalize_asset_url(it["url"]) for it in cover_res["items"]}
        hero_cover_role_urls = {
            _canonicalize_asset_url(it["url"])
            for it in hero_res["items"]
            if "cover" in it["asset_roles"]
        }
        self.assertEqual(
            cover_urls,
            {
                "https://cdn.ymgal.games/sp_ymgal.jpg",
                "https://www.kungal.com/sp_shared.jpg",
                "https://t.vndb.org/cv/sp_vndb.jpg",
                "https://lain.bgm.tv/pic/cover/l/sp_bgm.jpg",
            },
        )
        # 封面原图搜出的每一张图，在 Hero 查图的「封面源」角色中 100% 可见
        self.assertTrue(cover_urls.issubset(hero_cover_role_urls))
        self.assertEqual(hero_cover_role_urls, cover_urls)

        # 未配置 SGDB Key 时仅返回克制提示，不重复
        self.assertEqual(hero_res["warnings"], ["SteamGridDB 未配置"])

    async def test_hero_single_source_and_background_alias_and_warning_dedup(self) -> None:
        async def _fake_tgal_search(self_scraper, query: str, limit: int = 10):
            return [
                ScraperSearchResult(
                    source="touchgal",
                    source_id="tg1",
                    title="Summer Pockets",
                    cover_url="https://cdn.touchgal.io/tgal_cover.jpg",
                    background_url="https://cdn.touchgal.io/tgal_cover.jpg",
                )
            ]

        # 1. Hero 模式下单选 TouchGal，直接返回封面源候选且带 asset_role="cover"
        with patch.object(asset_search_mod.TouchGalScraper, "search", new=_fake_tgal_search):
            res_tgal = await search_asset_candidates(
                "hero",
                "Summer Pockets",
                source="touchgal",
                api_keys={"touchgal": "tgal_live_demo-secret"},
            )
        self.assertEqual(res_tgal["count"], 1)
        self.assertEqual(res_tgal["items"][0]["source"], "TouchGal")
        self.assertEqual(res_tgal["items"][0]["asset_role"], "cover")

        # 2. 未配置 SteamGridDB Key 时，Hero 查图单选 steamgriddb 告警不重复
        res_sgdb_no_key = await search_asset_candidates(
            "background",
            "Summer Pockets",
            source="steamgriddb",
            api_keys={},
        )
        self.assertEqual(res_sgdb_no_key["count"], 0)
        self.assertEqual(res_sgdb_no_key["warnings"], ["SteamGridDB 未配置"])


class HeroAssetSearchApiEndpointTestCase(unittest.IsolatedAsyncioTestCase):
    """端到端校验 /api/scraper/assets/search (hero/background) 与选中封面源应用到 Hero 不影响原封面"""

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="tsumugi_hero_asset_test_")
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

    async def test_api_hero_search_and_apply_cover_candidate_preserves_original_cover(self) -> None:
        async with self.session_maker() as db:
            game = Game(title="Summer Pockets", sub_title="サマーポケッツ")
            game.media = GameMediaPath(
                cover_path="assets/1/cover.webp",
                cover_thumb_path="assets/1/cover_thumb.webp",
                hero_bg_path="",
            )
            game.play_record = PlayRecord(total_seconds=0)
            db.add(game)
            await db.commit()
            game_id = game.id

        async def _override_get_db():
            async with self.session_maker() as session:
                yield session

        async def _fake_sgdb(asset_type, query, scraper, steam_appid=""):
            if asset_type == "hero":
                return [_cand("SteamGridDB", "https://cdn.sgdb.com/hero_api.png", width=1920, height=620)], []
            return [], []

        async def _fake_bgm(asset_type, query, scraper):
            if asset_type == "cover":
                return [_cand("Bangumi", "https://lain.bgm.tv/pic/cover/l/cover_for_hero.jpg")]
            return []

        async def _empty(*_args, **_kwargs):
            return []

        async def _fake_download_single(*, game_id: int, asset_type: str, url: str, proxy_url: str = ""):
            self.assertEqual(asset_type, "hero")
            self.assertEqual(url, "https://lain.bgm.tv/pic/cover/l/cover_for_hero.jpg")
            return {"path": f"assets/{game_id}/hero.webp"}

        app.dependency_overrides[get_db] = _override_get_db
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                with (
                    patch.object(asset_search_mod, "_fetch_sgdb_candidates", side_effect=_fake_sgdb),
                    patch.object(asset_search_mod, "_fetch_vndb_candidates", side_effect=_empty),
                    patch.object(asset_search_mod, "_fetch_steam_candidates", side_effect=_empty),
                    patch.object(asset_search_mod, "_fetch_bangumi_candidates", side_effect=_fake_bgm),
                    patch.object(asset_search_mod, "_fetch_touchgal_candidates", side_effect=_empty),
                    patch.object(asset_search_mod, "_fetch_generic_scraper_image_candidates", side_effect=_empty),
                ):
                    r_search = await client.get(
                        "/api/scraper/assets/search",
                        params={"asset_type": "hero", "q": "Summer Pockets", "source": "all"},
                    )
                    self.assertEqual(r_search.status_code, 200)
                    body = r_search.json()
                    self.assertEqual(body["count"], 2)
                    self.assertEqual(body["items"][0]["asset_role"], "hero")
                    self.assertEqual(body["items"][0]["asset_roles"], ["hero"])
                    self.assertEqual(body["items"][1]["asset_role"], "cover")
                    self.assertEqual(body["items"][1]["asset_roles"], ["cover"])
                    self.assertEqual(body["items"][1]["source"], "Bangumi")

                # 选中来自封面源的候选图并应用到 Hero 槽位，原封面路径与缩略图必须毫发无损
                with patch("backend.api.scraper.download_single_image_asset", side_effect=_fake_download_single):
                    r_apply = await client.post(
                        f"/api/scraper/assets/apply/{game_id}",
                        json={
                            "asset_type": "hero",
                            "url": "https://lain.bgm.tv/pic/cover/l/cover_for_hero.jpg",
                            "source": "Bangumi",
                            "mime_hint": "image",
                            "mode": "download",
                        },
                    )
                    self.assertEqual(r_apply.status_code, 200)
                    updated = r_apply.json()
                    self.assertEqual(updated["media"]["hero_bg_path"], f"assets/{game_id}/hero.webp")
                    self.assertEqual(updated["media"]["cover_path"], "assets/1/cover.webp")
                    self.assertEqual(updated["media"]["cover_thumb_path"], "assets/1/cover_thumb.webp")
        finally:
            app.dependency_overrides.pop(get_db, None)

    async def test_api_apply_local_current_cover_as_hero_copies_independently(self) -> None:
        """验证前端点击「当前封面」快捷项（local://cover）时，后端安全拷贝为独立 Hero 文件，绝不破坏原封面"""
        import io
        from PIL import Image
        from backend.api import scraper as scraper_api_mod
        from backend.services import media_service as media_service_mod

        fake_data_dir = self.tmp_dir / "data"
        fake_assets_dir = fake_data_dir / "assets"
        fake_game_dir = fake_assets_dir / "1"
        fake_game_dir.mkdir(parents=True, exist_ok=True)

        img_buf = io.BytesIO()
        Image.new("RGB", (600, 900), color=(40, 80, 120)).save(img_buf, format="WEBP")
        cover_bytes = img_buf.getvalue()
        cover_file = fake_game_dir / "cover.webp"
        thumb_file = fake_game_dir / "cover_thumb.webp"
        cover_file.write_bytes(cover_bytes)
        thumb_file.write_bytes(cover_bytes)

        async with self.session_maker() as db:
            game = Game(title="Summer Pockets", sub_title="サマーポケッツ")
            game.media = GameMediaPath(
                cover_path="assets/1/cover.webp",
                cover_thumb_path="assets/1/cover_thumb.webp",
                hero_bg_path="",
            )
            game.play_record = PlayRecord(total_seconds=0)
            db.add(game)
            await db.commit()
            game_id = game.id

        async def _override_get_db():
            async with self.session_maker() as session:
                yield session

        app.dependency_overrides[get_db] = _override_get_db
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                with (
                    patch.object(scraper_api_mod, "DATA_DIR", fake_data_dir),
                    patch.object(media_service_mod, "DATA_DIR", fake_data_dir),
                    patch.object(media_service_mod, "ASSETS_DIR", fake_assets_dir),
                ):
                    r_apply = await client.post(
                        f"/api/scraper/assets/apply/{game_id}",
                        json={
                            "asset_type": "hero",
                            "url": "local://cover",
                            "source": "当前封面",
                            "mime_hint": "image",
                            "mode": "download",
                        },
                    )
                    self.assertEqual(r_apply.status_code, 200)
                    updated = r_apply.json()

            hero_file = fake_assets_dir / str(game_id) / "hero.webp"
            self.assertTrue(hero_file.is_file(), "Hero file must be created independently")
            self.assertTrue(cover_file.is_file(), "Original cover must remain intact")
            self.assertTrue(thumb_file.is_file(), "Original cover thumb must remain intact")
            self.assertEqual(cover_file.read_bytes(), cover_bytes)
            self.assertEqual(updated["media"]["hero_bg_path"], f"assets/{game_id}/hero.webp")
            self.assertEqual(updated["media"]["cover_path"], "assets/1/cover.webp")
            self.assertEqual(updated["media"]["cover_thumb_path"], "assets/1/cover_thumb.webp")

            # 验证带 /static/data/ 前缀的历史封面路径也可安全解析复用
            from sqlalchemy import select as sa_select

            async with self.session_maker() as db:
                db_media = (
                    await db.execute(
                        sa_select(GameMediaPath).where(GameMediaPath.game_id == game_id)
                    )
                ).scalar_one()
                db_media.cover_path = "/static/data/assets/1/cover.webp"
                await db.commit()

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                with (
                    patch.object(scraper_api_mod, "DATA_DIR", fake_data_dir),
                    patch.object(media_service_mod, "DATA_DIR", fake_data_dir),
                    patch.object(media_service_mod, "ASSETS_DIR", fake_assets_dir),
                ):
                    r_apply_prefixed = await client.post(
                        f"/api/scraper/assets/apply/{game_id}",
                        json={
                            "asset_type": "hero",
                            "url": "local://cover",
                            "source": "当前封面",
                            "mime_hint": "image",
                            "mode": "download",
                        },
                    )
                    self.assertEqual(r_apply_prefixed.status_code, 200)
        finally:
            app.dependency_overrides.pop(get_db, None)


if __name__ == "__main__":
    unittest.main()
