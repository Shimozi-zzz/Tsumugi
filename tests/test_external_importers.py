from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zipfile

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from backend.db.database import Base, get_db
from backend.db.models import Game, GameMediaPath, PlayRecord
from backend.main import app
from backend.services import media_service
from backend.services.importers import (
    ImporterError,
    PlayniteImporter,
    VniteImporter,
    annotate_existing_games,
    execute_external_import,
)
from backend.services.importers.litedb_v4 import (
    read_litedb_v4_documents,
    write_litedb_v4_documents,
)
from backend.services.importers.playnite import PLAYNITE_STEAM_PLUGIN_ID


def _make_png_bytes(color: tuple[int, int, int] = (80, 140, 220), size: tuple[int, int] = (64, 96)) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(buf, format="PNG")
    return buf.getvalue()


class ExternalImportersTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="tsumugi_ext_test_")
        self.tmp_dir = Path(self._tmp.name)
        self.data_dir = self.tmp_dir / "tsumugi_data"
        self.assets_dir = self.data_dir / "assets"
        self.thumbs_dir = self.data_dir / "cache" / "thumbs"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.data_dir / "test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path.as_posix()}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_maker = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # 隔离 Tsumugi 媒体写入目录，避免污染真实 data/assets
        self._patch_data_dir = patch.object(media_service, "DATA_DIR", self.data_dir)
        self._patch_assets_dir = patch.object(media_service, "ASSETS_DIR", self.assets_dir)
        self._patch_thumbs_dir = patch.object(media_service, "THUMBS_CACHE_DIR", self.thumbs_dir)
        self._patch_data_dir.start()
        self._patch_assets_dir.start()
        self._patch_thumbs_dir.start()

    async def asyncTearDown(self) -> None:
        self._patch_data_dir.stop()
        self._patch_assets_dir.stop()
        self._patch_thumbs_dir.stop()
        await self.engine.dispose()
        self._tmp.cleanup()

    # ──────────────────── 1. Playnite LiteDB v4 + Playnite 9 + 去重合并 ────────────────────

    def _build_mock_playnite_litedb_library(self) -> tuple[Path, Path, Path]:
        lib_dir = self.tmp_dir / "playnite_lib"
        lib_dir.mkdir(parents=True, exist_ok=True)

        plat_id = uuid.uuid4()
        dev_id = uuid.uuid4()
        pub_id = uuid.uuid4()
        genre_id = uuid.uuid4()
        tag_id = uuid.uuid4()
        source_id = uuid.uuid4()
        status_done_id = uuid.uuid4()
        game1_id = uuid.uuid4()
        game2_id = uuid.uuid4()

        # 写入字典表 .db
        write_litedb_v4_documents(lib_dir / "platforms.db", [{"_id": plat_id, "Name": "PC (Windows)"}])
        write_litedb_v4_documents(
            lib_dir / "companies.db",
            [
                {"_id": dev_id, "Name": "Key"},
                {"_id": pub_id, "Name": "VisualArts"},
            ],
        )
        write_litedb_v4_documents(lib_dir / "genres.db", [{"_id": genre_id, "Name": "Visual Novel"}])
        write_litedb_v4_documents(lib_dir / "tags.db", [{"_id": tag_id, "Name": "泣系"}])
        write_litedb_v4_documents(lib_dir / "sources.db", [{"_id": source_id, "Name": "Steam"}])
        write_litedb_v4_documents(
            lib_dir / "completionstatuses.db",
            [{"_id": status_done_id, "Name": "Completed"}],
        )

        # 准备本地封面与背景图
        cover_file = lib_dir / "files" / str(game1_id) / "cover_art.png"
        bg_file = lib_dir / "files" / str(game1_id) / "bg_hero.png"
        cover_file.parent.mkdir(parents=True, exist_ok=True)
        cover_file.write_bytes(_make_png_bytes((220, 120, 90), (200, 300)))
        bg_file.write_bytes(_make_png_bytes((40, 80, 140), (320, 180)))

        # 构造一个超长 HTML 描述触发 ExtendPage 跨页写入与拼接测试
        long_note = "海风与蝉鸣交织的夏日回忆。" * 220
        html_desc = (
            "<p>Summer Pockets &amp; Reflection Blue</p>"
            f"<br/><div>{long_note}</div>"
            "<script>alert('xss')</script>"
        )

        write_litedb_v4_documents(
            lib_dir / "games.db",
            [
                {
                    "_id": game1_id,
                    "Name": "Summer Pockets",
                    "SortingName": "サマーポケッツ",
                    "Description": html_desc,
                    "ReleaseDate": {"ReleaseDate": "2018-06-29"},
                    "DeveloperIds": [dev_id],
                    "PublisherIds": [pub_id],
                    "GenreIds": [genre_id],
                    "TagIds": [tag_id],
                    "PlatformIds": [plat_id],
                    "SourceId": source_id,
                    "CompletionStatusId": status_done_id,
                    "Playtime": 18000,  # 5 小时（秒）
                    "LastActivity": datetime(2026, 8, 15, 14, 30, 0, tzinfo=timezone.utc),
                    "InstallDirectory": "D:\\Games\\SummerPockets",
                    "GameActions": [
                        {
                            "Type": 0,
                            "IsPlayAction": True,
                            "Path": "{InstallDir}\\SiglusEngine.exe",
                        }
                    ],
                    "CoverImage": f"{game1_id}\\cover_art.png",
                    "BackgroundImage": f"{game1_id}\\bg_hero.png",
                    "PluginId": uuid.UUID(PLAYNITE_STEAM_PLUGIN_ID),
                    "GameId": "897220",
                    "Links": [
                        {"Name": "VNDB", "Url": "https://vndb.org/v20424"},
                        {"Name": "Bangumi", "Url": "https://bgm.tv/subject/200763"},
                    ],
                },
                {
                    "_id": game2_id,
                    "Name": "CLANNAD",
                    "Description": "<p>光坂高校物语</p>",
                    "ReleaseDate": "2004-04-28",
                    "DeveloperIds": [dev_id],
                    "PublisherIds": [pub_id],
                    "Playtime": 3600,
                    "InstallDirectory": "D:\\Games\\CLANNAD",
                    "GameActions": [
                        {"Type": 0, "IsPlayAction": True, "Path": "{InstallDir}\\Siglus.exe"}
                    ],
                },
            ],
        )

        return lib_dir, cover_file, bg_file

    def test_playnite_litedb_v4_mapping_and_extend_page(self) -> None:
        lib_dir, cover_file, bg_file = self._build_mock_playnite_litedb_library()

        # 验证 LiteDB v4 二进制跨页读取
        docs = read_litedb_v4_documents(lib_dir / "games.db")
        self.assertEqual(len(docs), 2)

        importer = PlayniteImporter()
        candidates = importer.scan(str(lib_dir))
        self.assertEqual(len(candidates), 2)

        sp = next(c for c in candidates if c.name == "Summer Pockets")
        self.assertEqual(sp.source_app, "playnite")
        self.assertEqual(sp.original_name, "サマーポケッツ")
        self.assertEqual(sp.release_date, "2018-06-29")
        self.assertEqual(sp.developers, ["Key"])
        self.assertEqual(sp.publishers, ["VisualArts"])
        self.assertIn("Visual Novel", sp.tags)
        self.assertIn("泣系", sp.tags)
        self.assertEqual(sp.playtime_seconds, 18000)
        self.assertEqual(sp.play_status, "done")
        self.assertEqual(sp.platform_source, "Steam")
        self.assertEqual(sp.steam_appid, "897220")
        self.assertEqual(sp.vndb_id, "v20424")
        self.assertEqual(sp.bangumi_id, "200763")
        self.assertEqual(sp.executable_path, "D:\\Games\\SummerPockets\\SiglusEngine.exe")
        self.assertEqual(Path(sp.cover_path).resolve(), cover_file.resolve())
        self.assertEqual(Path(sp.background_path).resolve(), bg_file.resolve())
        # HTML 清洗与 script 移除检查
        self.assertIn("Summer Pockets & Reflection Blue", sp.description)
        self.assertNotIn("<p>", sp.description)
        self.assertNotIn("alert('xss')", sp.description)

    def test_playnite_9_json_and_config_detect(self) -> None:
        appdata = self.tmp_dir / "fake_appdata"
        pn_root = appdata / "Playnite"
        custom_lib = self.tmp_dir / "portable_playnite_lib"
        (custom_lib / "games").mkdir(parents=True, exist_ok=True)
        (custom_lib / "companies").mkdir(parents=True, exist_ok=True)

        pn_root.mkdir(parents=True, exist_ok=True)
        (pn_root / "config.json").write_text(
            json.dumps({"DatabasePath": str(custom_lib)}), encoding="utf-8"
        )

        comp_id = str(uuid.uuid4())
        (custom_lib / "companies" / f"{comp_id}.json").write_text(
            json.dumps({"Id": comp_id, "Name": "Yuzusoft"}), encoding="utf-8"
        )
        game_id = str(uuid.uuid4())
        (custom_lib / "games" / f"{game_id}.json").write_text(
            json.dumps(
                {
                    "Id": game_id,
                    "Name": "Senren * Banka",
                    "DeveloperIds": [comp_id],
                    "Playtime": 5400,
                    "InstallDirectory": "E:\\Gal\\SenrenBanka",
                    "GameActions": [{"Type": 0, "IsPlayAction": True, "Path": "{InstallDir}\\SenrenBanka.exe"}],
                }
            ),
            encoding="utf-8",
        )

        with patch.dict(os.environ, {"APPDATA": str(appdata)}):
            importer = PlayniteImporter()
            detected = importer.detect_path()
            self.assertTrue(detected.valid)
            self.assertEqual(Path(detected.detected_path).resolve(), custom_lib.resolve())

            scanned = importer.scan(detected.detected_path)
            self.assertEqual(len(scanned), 1)
            self.assertEqual(scanned[0].developers, ["Yuzusoft"])
            self.assertEqual(scanned[0].executable_path, "E:\\Gal\\SenrenBanka\\SenrenBanka.exe")

    async def test_playnite_dedup_skip_merge_and_independent_cover_copy(self) -> None:
        lib_dir, cover_file, bg_file = self._build_mock_playnite_litedb_library()
        importer = PlayniteImporter()
        candidates = importer.scan(str(lib_dir))

        async with self.session_maker() as db:
            # 预先在 Tsumugi 中放入已有条目 Summer Pockets（游玩时长更少、缺少封面与 vndb_id）
            existing = Game(
                title="Summer Pockets",
                synopsis="我自己写的简介，不应被覆盖",
                external_ids={},
                bangumi_id="",
                status="playing",
            )
            existing.media = GameMediaPath(cover_path="", hero_bg_path="", exe_path="")
            existing.play_record = PlayRecord(
                total_seconds=3600,
                last_played_at=datetime(2026, 7, 1, 10, 0, 0),
            )
            db.add(existing)
            await db.commit()
            existing_id = existing.id

        # 1) 验证 skip 策略：仅导入 CLANNAD，跳过 Summer Pockets
        async with self.session_maker() as db:
            summary_skip = await execute_external_import(db, candidates, duplicate_strategy="skip")
            self.assertEqual(summary_skip.imported, 1)
            self.assertEqual(summary_skip.skipped, 1)
            self.assertEqual(summary_skip.merged, 0)
            self.assertEqual(len(summary_skip.errors), 0)

        # 2) 验证 merge_playtime 策略：保留现有资料，游玩时长取 max，更新更晚 last_played_at，并顺手补齐封面和外部 ID
        async with self.session_maker() as db:
            sp_only = [c for c in candidates if c.name == "Summer Pockets"]
            summary_merge = await execute_external_import(
                db, sp_only, duplicate_strategy="merge_playtime"
            )
            self.assertEqual(summary_merge.merged, 1)
            self.assertEqual(summary_merge.imported, 0)
            self.assertEqual(summary_merge.skipped, 0)

            stmt = (
                select(Game)
                .where(Game.id == existing_id)
                .options(selectinload(Game.media), selectinload(Game.play_record))
            )
            merged_game = (await db.execute(stmt)).scalar_one()
            self.assertEqual(merged_game.synopsis, "我自己写的简介，不应被覆盖")
            self.assertEqual(merged_game.play_record.total_seconds, 18000)
            self.assertEqual(merged_game.play_record.last_played_at, datetime(2026, 8, 15, 14, 30, 0))
            self.assertEqual(merged_game.external_ids.get("steam"), "897220")
            self.assertEqual(merged_game.external_ids.get("vndb"), "v20424")
            self.assertEqual(merged_game.bangumi_id, "200763")
            self.assertEqual(merged_game.media.exe_path, "D:\\Games\\SummerPockets\\SiglusEngine.exe")
            self.assertTrue(merged_game.media.cover_path.startswith(f"assets/{existing_id}/cover"))
            self.assertTrue(merged_game.media.cover_thumb_path.endswith("cover_thumb.webp"))
            self.assertTrue(merged_game.media.hero_bg_path.startswith(f"assets/{existing_id}/hero"))

            copied_cover = self.data_dir / merged_game.media.cover_path
            copied_thumb = self.data_dir / merged_game.media.cover_thumb_path
            copied_hero = self.data_dir / merged_game.media.hero_bg_path
            self.assertTrue(copied_cover.is_file())
            self.assertTrue(copied_thumb.is_file())
            self.assertTrue(copied_hero.is_file())

            # 删除原 Playnite 封面与背景图，验证 Tsumugi 拷贝资产完全独立可用
            cover_file.unlink()
            bg_file.unlink()
            self.assertFalse(cover_file.exists())
            self.assertTrue(copied_cover.is_file())
            self.assertGreater(copied_cover.stat().st_size, 0)
            with Image.open(copied_cover) as im:
                self.assertEqual(im.size, (200, 300))

    # ──────────────────── 2. Vnite JSON / ZIP 备份解析、时长归一化与 LevelDB 友好提示 ────────────────────

    async def test_vnite_json_ms_vs_sec_normalization_and_zip_asset_copy(self) -> None:
        vnite_dir = self.tmp_dir / "vnite_export"
        vnite_dir.mkdir(parents=True, exist_ok=True)

        # 构造 JSON 备份（包含 nested Vnite v2/v3 毫秒时长 + flat 秒级时长）
        games_json = {
            "g_nested_ms": {
                "_id": "g_nested_ms",
                "metadata": {
                    "name": "白昼梦的青空",
                    "originalName": "白昼夢の青写真",
                    "releaseDate": "2020-09-25",
                    "description": "三段梦境与现实交织的故事。",
                    "developers": ["Laplacian"],
                    "publishers": ["Laplacian"],
                    "genres": ["视觉小说"],
                    "tags": ["悬疑", "催泪"],
                    "vndbId": "v26987",
                    "steamId": "1494450",
                    "relatedSites": [{"label": "Bangumi", "url": "https://bgm.tv/subject/295638"}],
                },
                "record": {
                    "playTime": 7200000,  # 2 小时（毫秒）
                    "lastRunDate": "2026-09-10T12:00:00.000Z",
                    "playStatus": "finished",
                    "timers": [
                        {"start": "2026-09-10T10:00:00.000Z", "end": "2026-09-10T12:00:00.000Z"}
                    ],
                },
            },
            "g_flat_sec": {
                "id": "g_flat_sec",
                "name": "千恋＊万花",
                "originalName": "千恋*万花",
                "releaseDate": "2016-07-29",
                "developers": "Yuzusoft",
                "tags": ["萌系", "和风"],
                "playTime": 3600,  # 1 小时（秒）
                "playStatus": "playing",
                "gamePath": "D:\\Galgame\\SenrenBanka\\SenrenBanka.exe",
                "vndbId": "19073",
                "bangumiId": "173620",
            },
        }

        local_json = {
            "g_nested_ms": {
                "_id": "g_nested_ms",
                "path": {"gamePath": "D:\\Galgame\\Cyanotype\\Cyanotype.exe"},
            }
        }

        # 创建 ZIP 备份（含 games.json + game-local.json + 封面与背景图片）
        zip_path = self.tmp_dir / "vnite_backup.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("database/games.json", json.dumps(games_json, ensure_ascii=False))
            zf.writestr("database/game-local.json", json.dumps(local_json, ensure_ascii=False))
            zf.writestr("images/g_nested_ms/cover.png", _make_png_bytes((20, 140, 210), (180, 260)))
            zf.writestr("images/g_nested_ms/background.png", _make_png_bytes((15, 30, 60), (320, 180)))

        importer = VniteImporter()
        candidates = importer.scan(str(zip_path))
        self.assertEqual(len(candidates), 2)

        cyan = next(c for c in candidates if c.external_id == "g_nested_ms")
        self.assertEqual(cyan.playtime_seconds, 7200)  # 7200000 ms -> 7200 s
        self.assertEqual(cyan.play_status, "done")
        self.assertEqual(cyan.vndb_id, "v26987")
        self.assertEqual(cyan.bangumi_id, "295638")
        self.assertEqual(cyan.steam_appid, "1494450")
        self.assertEqual(cyan.executable_path, "D:\\Galgame\\Cyanotype\\Cyanotype.exe")
        self.assertTrue(cyan.cover_path.startswith("zip://"))
        self.assertTrue(cyan.background_path.startswith("zip://"))

        senren = next(c for c in candidates if c.external_id == "g_flat_sec")
        self.assertEqual(senren.playtime_seconds, 3600)  # 3600 s -> 3600 s
        self.assertEqual(senren.play_status, "playing")
        self.assertEqual(senren.vndb_id, "v19073")
        self.assertEqual(senren.bangumi_id, "173620")
        self.assertEqual(senren.developers, ["Yuzusoft"])

        # 执行导入并验证 ZIP 内图片被独立拷贝到 Tsumugi 本地目录
        async with self.session_maker() as db:
            summary = await execute_external_import(db, candidates, duplicate_strategy="skip")
            self.assertEqual(summary.imported, 2)
            self.assertEqual(len(summary.errors), 0)

            stmt = (
                select(Game)
                .where(Game.title == "白昼梦的青空")
                .options(selectinload(Game.media), selectinload(Game.play_record))
            )
            imported_cyan = (await db.execute(stmt)).scalar_one()
            self.assertEqual(imported_cyan.play_record.total_seconds, 7200)
            self.assertTrue((self.data_dir / imported_cyan.media.cover_path).is_file())
            self.assertTrue((self.data_dir / imported_cyan.media.cover_thumb_path).is_file())
            self.assertTrue((self.data_dir / imported_cyan.media.hero_bg_path).is_file())

            # 删除原 ZIP 备份文件，验证已导入封面依然独立存在
            zip_path.unlink()
            self.assertTrue((self.data_dir / imported_cyan.media.cover_path).is_file())

    def test_vnite_leveldb_only_returns_friendly_error(self) -> None:
        ldb_dir = self.tmp_dir / "vnite_leveldb_only"
        (ldb_dir / "app" / "database").mkdir(parents=True, exist_ok=True)
        (ldb_dir / "app" / "database" / "CURRENT").write_text("MANIFEST-000001\n", encoding="utf-8")
        (ldb_dir / "app" / "database" / "000005.ldb").write_bytes(b"\x00\x01\x02binary")

        importer = VniteImporter()
        with self.assertRaises(ImporterError) as ctx:
            importer.scan(str(ldb_dir))
        self.assertIn("LevelDB", str(ctx.exception))
        self.assertIn(".json", str(ctx.exception))

    # ──────────────────── 3. 统一 API 路由端到端验证 ────────────────────

    async def test_external_import_api_endpoints(self) -> None:
        lib_dir, _, _ = self._build_mock_playnite_litedb_library()

        async def _override_get_db():
            async with self.session_maker() as session:
                yield session

        app.dependency_overrides[get_db] = _override_get_db
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                # 1. GET /detect
                r_det = await client.get("/api/import/external/playnite/detect")
                self.assertEqual(r_det.status_code, 200)
                self.assertEqual(r_det.json()["source"], "playnite")

                # 2. POST /scan
                r_scan = await client.post(
                    "/api/import/external/playnite/scan",
                    json={"path": str(lib_dir)},
                )
                self.assertEqual(r_scan.status_code, 200)
                scan_body = r_scan.json()
                self.assertEqual(scan_body["stats"]["total"], 2)
                self.assertEqual(scan_body["stats"]["new"], 2)
                self.assertEqual(scan_body["stats"]["existing"], 0)
                first_id = scan_body["items"][0]["external_id"]

                # 3. POST /execute
                r_exec = await client.post(
                    "/api/import/external/playnite/execute",
                    json={
                        "path": str(lib_dir),
                        "selected_ids": [first_id],
                        "duplicate_strategy": "skip",
                    },
                )
                self.assertEqual(r_exec.status_code, 200)
                exec_body = r_exec.json()
                self.assertEqual(exec_body["imported"], 1)
                self.assertEqual(exec_body["skipped"], 0)

                # 4. 再次 /scan 应识别 1 款已存在
                r_scan2 = await client.post(
                    "/api/import/external/playnite/scan",
                    json={"path": str(lib_dir)},
                )
                self.assertEqual(r_scan2.status_code, 200)
                self.assertEqual(r_scan2.json()["stats"]["existing"], 1)
                self.assertEqual(r_scan2.json()["stats"]["new"], 1)

                # 5. Vnite LevelDB 目录应返回 400 及友好文案而非 500
                ldb_dir = self.tmp_dir / "api_vnite_ldb"
                ldb_dir.mkdir(parents=True, exist_ok=True)
                (ldb_dir / "CURRENT").write_text("MANIFEST-000001\n", encoding="utf-8")
                r_err = await client.post(
                    "/api/import/external/vnite/scan",
                    json={"path": str(ldb_dir)},
                )
                self.assertEqual(r_err.status_code, 400)
                self.assertIn("LevelDB", r_err.json()["detail"])
        finally:
            app.dependency_overrides.pop(get_db, None)


if __name__ == "__main__":
    unittest.main()
