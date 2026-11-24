from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import json
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import httpx
from PIL import Image

from backend.api import media as media_api
from backend.api import system as system_api
from backend.main import app
from backend.services.backup_service import (
    create_auto_snapshot,
    export_library_backup_zip,
    list_auto_snapshots,
    restore_database_from_snapshot,
    restore_library_from_zip,
    validate_and_extract_backup_zip,
)
from backend.services.thumbnail_service import (
    build_thumb_api_url,
    clear_thumbnail_cache,
    get_or_create_webp_thumbnail,
    invalidate_thumbnails_for_game,
    invalidate_thumbnails_for_path,
    prewarm_cover_thumbnails,
    resolve_allowed_image_path,
)
from desktop import DesktopWindowApi


def _create_sample_sqlite_db(db_path: Path, titles: list[str], *, wal: bool = False) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        if wal:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL
            )
            """
        )
        conn.execute("DELETE FROM games")
        for t in titles:
            conn.execute("INSERT INTO games (title) VALUES (?)", (t,))
        conn.commit()
    finally:
        conn.close()


def _read_game_titles(db_path: Path) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT title FROM games ORDER BY id ASC").fetchall()
        return [str(r[0]) for r in rows]
    finally:
        conn.close()


class ThumbnailServiceTestCase(unittest.TestCase):
    """1. WebP 缩略图生成、透明图/EXIF 兼容、防路径穿越、缓存失效与降级测试"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name) / "data"
        self.assets_dir = self.data_dir / "assets" / "1"
        self.wallpapers_dir = self.data_dir / "wallpapers"
        self.thumbs_dir = self.data_dir / "thumbs"
        self.backups_dir = self.data_dir / "backups"
        for d in (self.assets_dir, self.wallpapers_dir, self.thumbs_dir, self.backups_dir):
            d.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_sm_md_webp_generation_and_no_upscale(self) -> None:
        # 大图 1200x600 -> sm(360px) / md(720px) 等比缩放为 WebP
        large_img = self.assets_dir / "cover.png"
        Image.new("RGB", (1200, 600), color=(30, 120, 200)).save(large_img, format="PNG")

        sm_path, sm_ok = get_or_create_webp_thumbnail(
            "assets/1/cover.png",
            size="sm",
            data_dir=self.data_dir,
            thumbs_dir=self.thumbs_dir,
        )
        self.assertTrue(sm_ok)
        self.assertEqual(sm_path.parent, self.thumbs_dir.resolve())
        self.assertEqual(sm_path.suffix, ".webp")
        with Image.open(sm_path) as out_sm:
            self.assertEqual(out_sm.format, "WEBP")
            self.assertEqual(out_sm.size, (360, 180))

        # 同时支持 /static/data/... URL 格式输入
        md_path, md_ok = get_or_create_webp_thumbnail(
            "/static/data/assets/1/cover.png?v=42",
            size="md",
            data_dir=self.data_dir,
            thumbs_dir=self.thumbs_dir,
        )
        self.assertTrue(md_ok)
        with Image.open(md_path) as out_md:
            self.assertEqual(out_md.format, "WEBP")
            self.assertEqual(out_md.size, (720, 360))

        # 小图 200x120 不放大
        small_img = self.assets_dir / "small.png"
        Image.new("RGB", (200, 120), color=(200, 80, 60)).save(small_img, format="PNG")
        small_thumb, small_ok = get_or_create_webp_thumbnail(
            "assets/1/small.png",
            size="sm",
            data_dir=self.data_dir,
            thumbs_dir=self.thumbs_dir,
        )
        self.assertTrue(small_ok)
        with Image.open(small_thumb) as out_small:
            self.assertEqual(out_small.size, (200, 120))

    def test_rgba_palette_transparency_and_exif_orientation(self) -> None:
        # RGBA 透明图保留 Alpha 通道
        rgba_src = self.assets_dir / "logo_rgba.png"
        rgba = Image.new("RGBA", (800, 400), color=(255, 100, 50, 0))
        rgba.putpixel((10, 10), (255, 100, 50, 180))
        rgba.save(rgba_src, format="PNG")

        rgba_thumb, ok1 = get_or_create_webp_thumbnail(
            "assets/1/logo_rgba.png",
            size="sm",
            data_dir=self.data_dir,
            thumbs_dir=self.thumbs_dir,
        )
        self.assertTrue(ok1)
        with Image.open(rgba_thumb) as im:
            self.assertEqual(im.format, "WEBP")
            self.assertIn("A", im.getbands())
            self.assertEqual(im.size, (360, 180))

        # 调色板 P 模式透明图正常转换不报错
        pal_src = self.assets_dir / "pal_alpha.png"
        pal = Image.new("P", (500, 250), color=0)
        pal.putpalette([0, 0, 0, 255, 0, 0] + [0] * (256 - 2) * 3)
        pal.info["transparency"] = 0
        pal.save(pal_src, format="PNG", transparency=0)

        pal_thumb, ok2 = get_or_create_webp_thumbnail(
            "assets/1/pal_alpha.png",
            size="sm",
            data_dir=self.data_dir,
            thumbs_dir=self.thumbs_dir,
        )
        self.assertTrue(ok2)
        with Image.open(pal_thumb) as im:
            self.assertEqual(im.format, "WEBP")
            self.assertIn("A", im.getbands())

        # EXIF Orientation=6 (顺时针旋转 90°): 800x400 原图纠正后变为竖图 400x800，缩放至 360x720
        exif_src = self.assets_dir / "rotated.jpg"
        base_jpg = Image.new("RGB", (800, 400), color=(10, 200, 90))
        exif = base_jpg.getexif()
        exif[0x0112] = 6
        base_jpg.save(exif_src, format="JPEG", exif=exif)

        exif_thumb, ok3 = get_or_create_webp_thumbnail(
            "assets/1/rotated.jpg",
            size="sm",
            data_dir=self.data_dir,
            thumbs_dir=self.thumbs_dir,
        )
        self.assertTrue(ok3)
        with Image.open(exif_thumb) as im:
            self.assertEqual(im.size, (360, 720))

    def test_path_traversal_and_disallowed_dirs_blocked(self) -> None:
        outside_file = Path(self._tmp.name) / "secret.png"
        Image.new("RGB", (100, 100)).save(outside_file, format="PNG")
        (self.backups_dir / "leak.png").write_bytes(outside_file.read_bytes())
        (self.data_dir / "tsumugi.db").write_bytes(b"sqlite")

        for bad_path in (
            "../secret.png",
            "assets/../../secret.png",
            str(outside_file),
            "/etc/passwd",
            "backups/leak.png",
            "tsumugi.db",
            "https://example.com/a.png",
            "assets/1/cover.png\x00.jpg",
        ):
            with self.assertRaises(PermissionError, msg=f"Should reject {bad_path!r}"):
                resolve_allowed_image_path(bad_path, data_dir=self.data_dir)

    def test_cache_invalidation_on_source_update_and_clear(self) -> None:
        src = self.assets_dir / "cover.png"
        Image.new("RGB", (800, 400), color=(255, 0, 0)).save(src, format="PNG")

        first_thumb, ok1 = get_or_create_webp_thumbnail(
            "assets/1/cover.png",
            size="sm",
            data_dir=self.data_dir,
            thumbs_dir=self.thumbs_dir,
        )
        self.assertTrue(ok1)
        self.assertTrue(first_thumb.is_file())

        # 替换原图并推进 mtime：自动生成新哈希缩略图并淘汰旧版本
        Image.new("RGB", (800, 400), color=(0, 0, 255)).save(src, format="PNG")
        new_mtime = src.stat().st_mtime + 10.0
        os.utime(src, (new_mtime, new_mtime))

        second_thumb, ok2 = get_or_create_webp_thumbnail(
            "assets/1/cover.png",
            size="sm",
            data_dir=self.data_dir,
            thumbs_dir=self.thumbs_dir,
        )
        self.assertTrue(ok2)
        self.assertNotEqual(first_thumb.name, second_thumb.name)
        self.assertFalse(first_thumb.exists())
        self.assertTrue(second_thumb.is_file())
        with Image.open(second_thumb) as im:
            r, _g, b = im.convert("RGB").getpixel((10, 10))
            self.assertGreater(b, r)

        # 游戏删除清理缩略图
        removed = invalidate_thumbnails_for_game(1, data_dir=self.data_dir, thumbs_dir=self.thumbs_dir)
        self.assertGreaterEqual(removed, 1)
        self.assertFalse(second_thumb.exists())

        # 预热 + 一键清空缩略图缓存
        prewarm_stats = prewarm_cover_thumbnails(
            ["assets/1/cover.png", "https://remote.example/a.png"],
            data_dir=self.data_dir,
            thumbs_dir=self.thumbs_dir,
        )
        self.assertEqual(prewarm_stats["generated"], 1)
        cleared = clear_thumbnail_cache(thumbs_dir=self.thumbs_dir)
        self.assertEqual(cleared["deleted_files"], 1)
        self.assertEqual(list(self.thumbs_dir.glob("*.webp")), [])

        # 工具函数构造轻量 API URL
        self.assertEqual(
            build_thumb_api_url("assets/1/cover.png", "sm"),
            "/api/media/thumb?path=assets/1/cover.png&size=sm",
        )
        self.assertEqual(build_thumb_api_url("https://example.com/a.png", "sm"), "")

    def test_corrupt_file_safely_degrades_to_original(self) -> None:
        corrupt = self.assets_dir / "broken.png"
        corrupt.write_bytes(b"not-a-valid-image-payload")

        out_path, is_thumb = get_or_create_webp_thumbnail(
            "assets/1/broken.png",
            size="sm",
            data_dir=self.data_dir,
            thumbs_dir=self.thumbs_dir,
        )
        self.assertFalse(is_thumb)
        self.assertEqual(out_path, corrupt.resolve())
        self.assertEqual(invalidate_thumbnails_for_path("assets/1/broken.png", data_dir=self.data_dir, thumbs_dir=self.thumbs_dir), 0)

    def test_http_thumb_endpoint_cache_headers_and_traversal_403(self) -> None:
        src = self.assets_dir / "card.png"
        Image.new("RGB", (900, 450), color=(40, 180, 120)).save(src, format="PNG")

        async def _run() -> None:
            transport = httpx.ASGITransport(app=app)
            with (
                patch("backend.services.thumbnail_service.DATA_DIR", self.data_dir),
                patch("backend.services.thumbnail_service.THUMBS_DIR", self.thumbs_dir),
                patch("backend.services.thumbnail_service.THUMBS_CACHE_DIR", self.data_dir / "cache" / "thumbs"),
            ):
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    ok_resp = await client.get("/api/media/thumb", params={"path": "assets/1/card.png", "size": "sm"})
                    self.assertEqual(ok_resp.status_code, 200)
                    self.assertEqual(ok_resp.headers.get("content-type"), "image/webp")
                    self.assertIn("immutable", ok_resp.headers.get("cache-control", ""))

                    bad_resp = await client.get("/api/media/thumb", params={"path": "../../etc/passwd", "size": "sm"})
                    self.assertEqual(bad_resp.status_code, 403)

                    clear_resp = await client.post("/api/system/cache/clear-thumbs")
                    self.assertEqual(clear_resp.status_code, 200)
                    body = clear_resp.json()
                    self.assertTrue(body["cleared"])
                    self.assertGreaterEqual(body["deleted_files"], 1)

        asyncio.run(_run())


class SqliteAutoSnapshotTestCase(unittest.TestCase):
    """2. SQLite backup() 在线热备快照、10 分钟节流与最多保留 5 份轮转清理测试"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name) / "data"
        self.db_path = self.data_dir / "tsumugi.db"
        self.auto_dir = self.data_dir / "backups" / "auto"
        _create_sample_sqlite_db(self.db_path, ["Summer Pockets", "CLANNAD"], wal=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_wal_online_hot_backup_throttle_and_five_snapshot_rotation(self) -> None:
        # 故意保持一个开启的 WAL 写连接（存在未 checkpoint 的 WAL 帧），验证 sqlite3.backup() 完整性
        live_conn = sqlite3.connect(str(self.db_path))
        try:
            live_conn.execute("INSERT INTO games (title) VALUES (?)", ("AIR (WAL Uncheckpointed)",))
            live_conn.commit()

            t0 = datetime(2026, 11, 24, 10, 0, 0)
            snap1 = create_auto_snapshot(
                tag="auto",
                force=False,
                min_interval_seconds=600,
                max_keep=5,
                db_path=self.db_path,
                auto_dir=self.auto_dir,
                now=t0,
            )
            self.assertIsNotNone(snap1)
            assert snap1 is not None
            self.assertTrue(snap1["filename"].startswith("tsumugi_auto_"))
            # 快照必须包含刚刚提交到 WAL 的新记录
            snap1_titles = _read_game_titles(self.auto_dir / snap1["filename"])
            self.assertIn("AIR (WAL Uncheckpointed)", snap1_titles)

            # 3 分钟后再触发（< 10 分钟）：应静默跳过
            skipped = create_auto_snapshot(
                tag="auto",
                force=False,
                min_interval_seconds=600,
                max_keep=5,
                db_path=self.db_path,
                auto_dir=self.auto_dir,
                now=t0 + timedelta(minutes=3),
            )
            self.assertIsNone(skipped)

            # 连续跨越 10 分钟间隔生成共 7 份自动快照 -> 自动轮转后严格只保留最新 5 份
            created_names: list[str] = [snap1["filename"]]
            for i in range(1, 7):
                s = create_auto_snapshot(
                    tag="auto",
                    force=False,
                    min_interval_seconds=600,
                    max_keep=5,
                    db_path=self.db_path,
                    auto_dir=self.auto_dir,
                    now=t0 + timedelta(minutes=15 * i),
                )
                self.assertIsNotNone(s)
                assert s is not None
                created_names.append(s["filename"])

            auto_files = sorted(p.name for p in self.auto_dir.glob("tsumugi_auto_*.db"))
            self.assertEqual(len(auto_files), 5)
            self.assertEqual(auto_files, sorted(created_names[-5:]))

            # 保护快照独立保留、不挤占 auto 计数
            pre_snap = create_auto_snapshot(
                tag="pre_import",
                force=True,
                db_path=self.db_path,
                auto_dir=self.auto_dir,
                now=t0 + timedelta(hours=3),
            )
            self.assertIsNotNone(pre_snap)
            assert pre_snap is not None
            self.assertEqual(pre_snap["tag"], "pre_import")
            all_snaps = list_auto_snapshots(auto_dir=self.auto_dir)
            self.assertEqual(len(all_snaps), 6)
        finally:
            live_conn.close()


class FullLibraryBackupAndRestoreTestCase(unittest.TestCase):
    """3. 整库 .zip 导出过滤、Zip Slip 拦截、安全恢复（数据一致性与 -wal/-shm 清理）及快照回滚测试"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.data_dir = self.root / "data"
        self.db_path = self.data_dir / "tsumugi.db"
        self.assets_dir = self.data_dir / "assets" / "1"
        self.wallpapers_dir = self.data_dir / "wallpapers"
        self.thumbs_dir = self.data_dir / "thumbs"
        self.backups_dir = self.data_dir / "backups"
        self.auto_dir = self.backups_dir / "auto"
        for d in (self.assets_dir, self.wallpapers_dir, self.thumbs_dir, self.auto_dir):
            d.mkdir(parents=True, exist_ok=True)

        _create_sample_sqlite_db(self.db_path, ["White Album 2", "Steins;Gate"], wal=True)
        (self.data_dir / "settings.json").write_text(
            json.dumps({"scraper_sources": {"enabled_sources": {"vndb": True}}}),
            encoding="utf-8",
        )
        Image.new("RGB", (600, 800), color=(90, 60, 140)).save(self.assets_dir / "cover.webp", format="WEBP")
        Image.new("RGB", (1280, 720), color=(20, 40, 60)).save(self.wallpapers_dir / "bg.webp", format="WEBP")
        # 本地 PV / OP 影音缓存
        (self.assets_dir / "pv.mp4").write_bytes(b"fake-mp4-video-data" * 50)
        (self.assets_dir / "bgm.m4a").write_bytes(b"fake-m4a-audio-data" * 20)
        # 应严格排除的干扰文件
        (self.thumbs_dir / "cached_thumb.webp").write_bytes(b"thumb")
        (self.auto_dir / "tsumugi_auto_old.db").write_bytes(b"old-backup")
        (self.data_dir / "tsumugi.log").write_text("log line", encoding="utf-8")
        (self.assets_dir / "pv.downloading.tmp").write_bytes(b"partial")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_export_excludes_noise_and_respects_include_videos(self) -> None:
        zip_no_video = self.root / "backup_no_video.zip"
        res_light = export_library_backup_zip(
            zip_no_video,
            include_videos=False,
            data_dir=self.data_dir,
            db_path=self.db_path,
        )
        self.assertTrue(res_light["exported"])
        self.assertEqual(res_light["manifest"]["game_count"], 2)
        self.assertFalse(res_light["manifest"]["include_videos"])

        with zipfile.ZipFile(zip_no_video, "r") as zf:
            names = set(zf.namelist())
            self.assertIn("manifest.json", names)
            self.assertIn("tsumugi.db", names)
            self.assertIn("settings.json", names)
            self.assertIn("assets/1/cover.webp", names)
            self.assertIn("wallpapers/bg.webp", names)
            # 严格排除 backups / thumbs / log / tmp / wal / shm / 影音
            self.assertNotIn("assets/1/pv.mp4", names)
            self.assertNotIn("assets/1/bgm.m4a", names)
            self.assertFalse(any(n.startswith(("backups/", "thumbs/")) for n in names))
            self.assertFalse(any(n.endswith((".log", ".tmp", "-wal", "-shm")) for n in names))

        zip_with_video = self.root / "backup_with_video.zip"
        res_full = export_library_backup_zip(
            zip_with_video,
            include_videos=True,
            data_dir=self.data_dir,
            db_path=self.db_path,
        )
        self.assertTrue(res_full["manifest"]["include_videos"])
        with zipfile.ZipFile(zip_with_video, "r") as zf:
            names = set(zf.namelist())
            self.assertIn("assets/1/pv.mp4", names)
            self.assertIn("assets/1/bgm.m4a", names)
            self.assertFalse(any(n.startswith(("backups/", "thumbs/")) for n in names))

    def test_zip_slip_and_corrupt_db_rejected(self) -> None:
        # 1. 构造含 ../ 目录穿越的恶意 Zip Slip 压缩包
        malicious_zip = self.root / "evil_slip.zip"
        with zipfile.ZipFile(malicious_zip, "w") as zf:
            zf.writestr("../escape.txt", "pwned")
            zf.write(self.db_path, arcname="tsumugi.db")

        with self.assertRaises(ValueError) as ctx:
            validate_and_extract_backup_zip(malicious_zip, self.root / "extract_evil")
        self.assertIn("Zip Slip", str(ctx.exception))
        self.assertFalse((self.root / "escape.txt").exists())

        # 2. 构造含绝对路径的恶意 Zip
        abs_zip = self.root / "evil_abs.zip"
        with zipfile.ZipFile(abs_zip, "w") as zf:
            zf.writestr("/tmp/evil_abs_file.txt", "pwned")
            zf.write(self.db_path, arcname="tsumugi.db")
        with self.assertRaises(ValueError):
            validate_and_extract_backup_zip(abs_zip, self.root / "extract_abs")

        # 3. 损坏的 tsumugi.db 应被 PRAGMA integrity_check 拦截
        corrupt_zip = self.root / "corrupt_db.zip"
        with zipfile.ZipFile(corrupt_zip, "w") as zf:
            zf.writestr("tsumugi.db", b"definitely-corrupt-sqlite-bytes-1234567890")
        with self.assertRaises(ValueError):
            validate_and_extract_backup_zip(corrupt_zip, self.root / "extract_corrupt")

    def test_restore_zip_and_snapshot_rollback_clean_wal_shm_and_preserve_consistency(self) -> None:
        # 先导出原始状态（White Album 2, Steins;Gate）
        backup_zip = self.root / "good_backup.zip"
        export_library_backup_zip(
            backup_zip,
            include_videos=False,
            data_dir=self.data_dir,
            db_path=self.db_path,
        )

        # 修改当前运行库为新内容，并保持活跃 WAL 连接（模拟真实服务运行态）
        _create_sample_sqlite_db(self.db_path, ["Corrupted Or Unwanted Game"], wal=True)
        wal_file = Path(f"{self.db_path}-wal")
        shm_file = Path(f"{self.db_path}-shm")
        (self.thumbs_dir / "old_thumb.webp").write_bytes(b"stale-thumb")
        (self.data_dir / "settings.json").write_text(
            json.dumps({"scraper_sources": {"enabled_sources": {"vndb": False}}}),
            encoding="utf-8",
        )

        disposed = {"count": 0}
        reinited = {"count": 0}

        async def _fake_dispose() -> None:
            disposed["count"] += 1
            # 模拟连接池释放后磁盘仍残留旧 -wal / -shm 伴随文件，验证恢复逻辑主动清理它们
            wal_file.write_bytes(b"stale-wal-bytes")
            shm_file.write_bytes(b"stale-shm-bytes")

        async def _fake_reinit() -> None:
            reinited["count"] += 1

        result = asyncio.run(
            restore_library_from_zip(
                backup_zip,
                dispose_engine=_fake_dispose,
                reinit_db=_fake_reinit,
                data_dir=self.data_dir,
                db_path=self.db_path,
                auto_dir=self.auto_dir,
                thumbs_dir=self.thumbs_dir,
            )
        )

        self.assertTrue(result["restored"])
        self.assertEqual(disposed["count"], 1)
        self.assertEqual(reinited["count"], 1)
        # 验证恢复前自动生成了 pre_restore 保护快照
        self.assertIsNotNone(result["safety_snapshot"])
        self.assertTrue(str(result["safety_snapshot"]).startswith("tsumugi_pre_restore_"))
        # 验证残留 -wal / -shm 与旧缩略图缓存均被清理
        self.assertFalse(wal_file.exists())
        self.assertFalse(shm_file.exists())
        self.assertIn("tsumugi.db-wal", result["removed_sidecars"])
        self.assertIn("tsumugi.db-shm", result["removed_sidecars"])
        self.assertEqual(list(self.thumbs_dir.glob("*.webp")), [])
        # 验证数据库记录与 settings.json 完全恢复一致
        self.assertEqual(_read_game_titles(self.db_path), ["White Album 2", "Steins;Gate"])
        restored_cfg = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
        self.assertTrue(restored_cfg["scraper_sources"]["enabled_sources"]["vndb"])

        # 再测试快照回滚：回滚至刚创建的 pre_restore 快照（应回到 Corrupted Or Unwanted Game）
        wal_file.write_bytes(b"another-wal")
        rollback_res = asyncio.run(
            restore_database_from_snapshot(
                str(result["safety_snapshot"]),
                dispose_engine=_fake_dispose,
                reinit_db=_fake_reinit,
                data_dir=self.data_dir,
                db_path=self.db_path,
                auto_dir=self.auto_dir,
                thumbs_dir=self.thumbs_dir,
            )
        )
        self.assertTrue(rollback_res["restored"])
        self.assertFalse(wal_file.exists())
        self.assertEqual(_read_game_titles(self.db_path), ["Corrupted Or Unwanted Game"])

        # 快照路径穿越校验
        with self.assertRaises(ValueError):
            asyncio.run(
                restore_database_from_snapshot(
                    "../tsumugi.db",
                    dispose_engine=_fake_dispose,
                    reinit_db=_fake_reinit,
                    data_dir=self.data_dir,
                    db_path=self.db_path,
                    auto_dir=self.auto_dir,
                    thumbs_dir=self.thumbs_dir,
                )
            )


class DesktopBackupDialogGuardTestCase(unittest.TestCase):
    """4. 验证 desktop.py 新增原生文件对话框及导出直写方法在非 Windows/Linux 下的安全性"""

    def test_dialog_methods_safe_when_detached_or_mocked(self) -> None:
        api = DesktopWindowApi(logging.getLogger("test.desktop.backup_dialogs"), platform="linux")
        self.assertEqual(api.select_backup_save_path("test_backup"), "")
        self.assertEqual(api.select_backup_open_path(), "")
        self.assertEqual(api.select_save_file_path("note_card", ["PNG Image (*.png)"], ".png"), "")

    def test_write_export_file_binary_and_validation(self) -> None:
        import base64

        api = DesktopWindowApi(logging.getLogger("test.desktop.export_write"), platform="linux")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "note-share.png"
            payload = base64.b64encode(b"\x89PNG\r\n\x1a\nfake-png-body").decode("ascii")
            res = api.write_export_file(str(target), payload)
            self.assertTrue(res["saved"])
            self.assertEqual(target.read_bytes(), b"\x89PNG\r\n\x1a\nfake-png-body")

            err_empty = api.write_export_file("", payload)
            self.assertFalse(err_empty["saved"])
            err_bad_b64 = api.write_export_file(str(target), "not-valid-base64!!!")
            self.assertFalse(err_bad_b64["saved"])


if __name__ == "__main__":
    unittest.main()
