from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.api import media as media_api
from backend.api import scraper as scraper_api
from backend.db.database import Base, get_db
from backend.db.models import Game, GameMediaPath, PlayRecord
from backend.main import app
from backend.scrapers.steam import parse_steam_movies
from backend.services import media_service
from backend.services.media_service import (
    MediaDownloadError,
    _download_pv_with_ytdlp_sync,
    build_ytdlp_pv_options,
    download_pv_to_local,
    format_download_error_zh,
)
from backend.services.task_manager import task_manager


class FormatDownloadErrorZhTestCase(unittest.TestCase):
    """1. 下载异常中文化映射单元测试（绝不向前端暴露英文 CLI 噪声）"""

    _FORBIDDEN_CLI_NOISE = (
        "ERROR:",
        "--list-formats",
        "Requested format",
        "hls_264_master",
        "[generic]",
        "Traceback",
    )

    def _assert_clean_zh(self, msg: str) -> None:
        self.assertTrue(msg.strip(), "Chinese message must not be empty")
        self.assertTrue(
            any("\u4e00" <= ch <= "\u9fff" for ch in msg),
            f"Expected Chinese characters in: {msg!r}",
        )
        for bad in self._FORBIDDEN_CLI_NOISE:
            self.assertNotIn(bad, msg, f"Raw CLI noise {bad!r} leaked into: {msg!r}")

    def test_requested_format_not_available_steam_hls(self) -> None:
        raw = (
            "ERROR: [generic] hls_264_master: Requested format is not available. "
            "Use --list-formats for a list of available formats"
        )
        msg_video = format_download_error_zh(raw, media_kind="video")
        self._assert_clean_zh(msg_video)
        self.assertEqual(
            msg_video,
            "该视频源暂无兼容的本地下载格式，已保留在线链接可直接播放，或稍后重试",
        )

        msg_audio = format_download_error_zh(raw, media_kind="audio")
        self._assert_clean_zh(msg_audio)
        self.assertEqual(
            msg_audio,
            "该音频源暂无兼容的本地下载格式，已保留在线链接可直接播放，或稍后重试",
        )

    def test_missing_ffmpeg_mapping(self) -> None:
        msg = format_download_error_zh(
            "ERROR: You have requested merging of multiple formats but ffmpeg is not installed",
            media_kind="video",
        )
        self._assert_clean_zh(msg)
        self.assertIn("FFmpeg", msg)
        self.assertIn("已保留在线链接", msg)

    def test_http_403_412_and_404_410_mapping(self) -> None:
        for raw_403 in (
            "ERROR: unable to download video data: HTTP Error 403: Forbidden",
            "HTTP Error 412: Precondition Failed",
        ):
            msg = format_download_error_zh(raw_403, media_kind="video")
            self._assert_clean_zh(msg)
            self.assertIn("拒绝访问", msg)

        req = httpx.Request("GET", "https://cdn.example.com/pv.mp4")
        err_404 = httpx.HTTPStatusError(
            "Not Found",
            request=req,
            response=httpx.Response(404, request=req),
        )
        msg_404 = format_download_error_zh(err_404, media_kind="video")
        self._assert_clean_zh(msg_404)
        self.assertIn("已失效（404）", msg_404)

    def test_timeout_proxy_and_unsupported_url_mapping(self) -> None:
        msg_timeout = format_download_error_zh(httpx.ReadTimeout("timed out"), media_kind="video")
        self._assert_clean_zh(msg_timeout)
        self.assertIn("超时", msg_timeout)

        msg_proxy = format_download_error_zh("ProxyError: Unable to connect to proxy", media_kind="audio")
        self._assert_clean_zh(msg_proxy)
        self.assertIn("超时", msg_proxy)

        msg_unsup = format_download_error_zh(
            "ERROR: Unsupported URL: https://unknown.example.org/watch/1",
            media_kind="video",
        )
        self._assert_clean_zh(msg_unsup)
        self.assertEqual(msg_unsup, "暂不支持下载该平台链接，已保留在线链接供播放")

    def test_unknown_raw_exception_fallback(self) -> None:
        msg = format_download_error_zh(RuntimeError("Some raw unexpected english error"), media_kind="video")
        self._assert_clean_zh(msg)
        self.assertEqual(msg, "本地视频下载失败，已保留在线链接可直接播放")


class SteamMoviesAndHlsDownloadTestCase(unittest.IsolatedAsyncioTestCase):
    """2. Steam 预告片直链优先级提取 + HLS yt-dlp 格式放宽与自动重试测试"""

    def test_parse_steam_movies_strict_priority_and_fallbacks(self) -> None:
        movies = [
            {
                "id": 1001,
                "name": "Official Trailer (Full)",
                "thumbnail": "//cdn.example/thumb1.jpg",
                "hls_h264": "https://cdn.example/hls_264_master.m3u8",
                "dash_h264": "https://cdn.example/dash_264.mpd",
                "webm": {
                    "480": "https://cdn.example/movie480.webm",
                    "max": "https://cdn.example/movie_max.webm",
                },
                "mp4": {
                    "480": "https://cdn.example/movie480.mp4",
                    "max": "https://cdn.example/movie_max.mp4",
                },
            },
            {
                "id": 1002,
                "name": "WebM + HLS Only Trailer",
                "thumbnail": "https://cdn.example/thumb2.jpg",
                "hls_h264": "https://cdn.example/only_hls.m3u8",
                "webm": {
                    "max": "https://cdn.example/only_max.webm",
                },
            },
            {
                "id": 1003,
                "name": "HLS Only Trailer",
                "thumbnail": "https://cdn.example/thumb3.jpg",
                "hls_h264": "https://cdn.example/pure_hls_264_master.m3u8",
                "dash_h264": "https://cdn.example/pure_dash.mpd",
            },
        ]

        parsed = parse_steam_movies(movies, app_name="Test Game", appid="12345")
        self.assertEqual(len(parsed), 3)

        # 第一条：严格优先 mp4.max，fallback_urls 依次为 mp4.480 > webm.max > webm.480 > hls > dash
        first = parsed[0]
        self.assertEqual(first["url"], "https://cdn.example/movie_max.mp4")
        self.assertEqual(first["mime_hint"], "mp4")
        self.assertEqual(first["thumb_url"], "https://cdn.example/thumb1.jpg")
        self.assertEqual(
            first["fallback_urls"],
            [
                "https://cdn.example/movie480.mp4",
                "https://cdn.example/movie_max.webm",
                "https://cdn.example/movie480.webm",
                "https://cdn.example/hls_264_master.m3u8",
                "https://cdn.example/dash_264.mpd",
            ],
        )

        # 第二条：无 mp4 时优先 webm.max 而非 hls_h264
        second = parsed[1]
        self.assertEqual(second["url"], "https://cdn.example/only_max.webm")
        self.assertEqual(second["mime_hint"], "webm")
        self.assertEqual(second["fallback_urls"], ["https://cdn.example/only_hls.m3u8"])

        # 第三条：仅有 hls/dash 时优先 hls_h264
        third = parsed[2]
        self.assertEqual(third["url"], "https://cdn.example/pure_hls_264_master.m3u8")
        self.assertEqual(third["mime_hint"], "hls")
        self.assertEqual(third["fallback_urls"], ["https://cdn.example/pure_dash.mpd"])

    def test_build_ytdlp_pv_options_no_ext_mp4_restriction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game_dir = Path(tmp)

            opts_ffmpeg = build_ytdlp_pv_options(
                game_dir,
                url="https://video.akamai.steamstatic.com/store_trailers/1/hls_264_master.m3u8",
                has_ffmpeg=True,
            )
            self.assertEqual(opts_ffmpeg["format"], "bestvideo*+bestaudio/best")
            self.assertEqual(opts_ffmpeg["merge_output_format"], "mp4")
            self.assertNotIn("[ext=mp4]", opts_ffmpeg["format"])

            opts_no_ffmpeg = build_ytdlp_pv_options(
                game_dir,
                url="https://video.akamai.steamstatic.com/store_trailers/1/hls_264_master.m3u8",
                has_ffmpeg=False,
            )
            self.assertEqual(opts_no_ffmpeg["format"], "best[vcodec!=none][acodec!=none]/best")
            self.assertNotIn("merge_output_format", opts_no_ffmpeg)
            self.assertNotIn("[ext=mp4]", opts_no_ffmpeg["format"])

    def test_ytdlp_hls_requested_format_triggers_relaxed_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game_dir = Path(tmp)
            attempted_formats: list[str] = []

            class _FakeYoutubeDL:
                def __init__(self, opts: dict) -> None:
                    self.opts = opts

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def extract_info(self, url: str, download: bool = True):
                    attempted_formats.append(str(self.opts.get("format")))
                    if len(attempted_formats) == 1:
                        raise RuntimeError(
                            "ERROR: [generic] hls_264_master: Requested format is not available. "
                            "Use --list-formats for a list of available formats"
                        )
                    out = game_dir / "pv.downloading.mp4"
                    out.write_bytes(b"\x00\x00\x00\x18ftypmp42fakevideo")
                    return {"id": "hls_264_master", "ext": "mp4"}

            with (
                patch.object(media_service.shutil, "which", return_value="/usr/bin/ffmpeg"),
                patch.object(media_service.yt_dlp, "YoutubeDL", _FakeYoutubeDL),
            ):
                downloaded = _download_pv_with_ytdlp_sync(
                    game_id=9001,
                    url="https://video.akamai.steamstatic.com/store_trailers/1/hls_264_master.m3u8",
                    game_dir=game_dir,
                    proxy_url="",
                )

            self.assertEqual(attempted_formats, ["bestvideo*+bestaudio/best", "b/bv*+ba/best"])
            self.assertTrue(downloaded.exists())
            self.assertEqual(downloaded.name, "pv.downloading.mp4")

    async def test_download_pv_hls_fallback_to_direct_mp4_and_zh_error_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            assets_dir = data_dir / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)

            async def _fake_direct_stream(game_id: int, url: str, game_dir: Path, proxy_url: str, ext: str = ".mp4") -> Path:
                p = game_dir / f"pv.downloading{ext}"
                p.write_bytes(b"FAKE_MP4_BYTES_123456")
                return p

            with (
                patch.object(media_service, "DATA_DIR", data_dir),
                patch.object(media_service, "ASSETS_DIR", assets_dir),
            ):
                # 场景 A：HLS yt-dlp 失败，但存在 Steam 备用直链 mp4 -> 自动回退直链下载成功
                with (
                    patch.object(
                        media_service,
                        "_download_pv_with_ytdlp_sync",
                        side_effect=RuntimeError("hls_264_master: Requested format is not available"),
                    ),
                    patch.object(
                        media_service,
                        "_download_direct_video_stream",
                        new=AsyncMock(side_effect=_fake_direct_stream),
                    ) as mock_direct,
                ):
                    rel_path = await download_pv_to_local(
                        game_id=8801,
                        url="https://video.akamai.steamstatic.com/store_trailers/1/hls_264_master.m3u8",
                        fallback_urls=["https://video.akamai.steamstatic.com/store_trailers/1/movie_max.mp4"],
                    )
                    self.assertEqual(rel_path, "assets/8801/pv.mp4")
                    self.assertTrue((assets_dir / "8801" / "pv.mp4").exists())
                    mock_direct.assert_awaited_once()
                    task = task_manager.get_task(8801, "pv")
                    self.assertIsNotNone(task)
                    self.assertEqual(task["status"], "done")

                # 场景 B：HLS 下载彻底失败且无可用直链 -> 抛出 MediaDownloadError，任务状态写入纯中文报错
                with patch.object(
                    media_service,
                    "_download_pv_with_ytdlp_sync",
                    side_effect=RuntimeError(
                        "ERROR: [generic] hls_264_master: Requested format is not available. "
                        "Use --list-formats for a list of available formats"
                    ),
                ):
                    with self.assertRaises(MediaDownloadError) as ctx:
                        await download_pv_to_local(
                            game_id=8802,
                            url="https://video.akamai.steamstatic.com/store_trailers/2/hls_264_master.m3u8",
                        )
                    self.assertEqual(
                        ctx.exception.zh_message,
                        "该视频源暂无兼容的本地下载格式，已保留在线链接可直接播放，或稍后重试",
                    )
                    err_task = task_manager.get_task(8802, "pv")
                    self.assertIsNotNone(err_task)
                    self.assertEqual(err_task["status"], "error")
                    self.assertNotIn("Requested format", err_task["message"])
                    self.assertNotIn("--list-formats", err_task["message"])
                    self.assertNotIn("ERROR:", err_task["message"])
                    self.assertIn("已保留在线链接可直接播放", err_task["message"])


class MediaThreeModeApiTestCase(unittest.IsolatedAsyncioTestCase):
    """3. 导入三模式（none / link_only / download）与本地缓存互转接口集成测试"""

    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_root = Path(self._tmpdir.name)
        self.assets_dir = self.tmp_root / "assets"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        db_path = self.tmp_root / "test_media_modes.db"

        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        self.session_maker = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async def _override_get_db():
            async with self.session_maker() as session:
                yield session

        app.dependency_overrides[get_db] = _override_get_db

    async def asyncTearDown(self) -> None:
        app.dependency_overrides.pop(get_db, None)
        await self.engine.dispose()
        self._tmpdir.cleanup()

    async def test_import_three_modes_and_download_dispatch_control(self) -> None:
        pv_remote = "https://video.akamai.steamstatic.com/store_trailers/999/movie_max.mp4"
        pv_fallback = "https://video.akamai.steamstatic.com/store_trailers/999/movie480.mp4"
        op_remote = "https://www.bilibili.com/video/BV1xx411c7mD"

        pv_mock = AsyncMock(return_value=None)
        bgm_mock = AsyncMock(return_value=None)
        auto_bgm_mock = AsyncMock(return_value=None)

        with (
            patch.object(scraper_api, "download_game_assets", new=AsyncMock(return_value={})),
            patch.object(scraper_api, "_background_download_pv", new=pv_mock),
            patch.object(scraper_api, "_background_download_selected_bgm", new=bgm_mock),
            patch.object(scraper_api, "_background_auto_fetch_bgm", new=auto_bgm_mock),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                # 1) mode = none（即便传入了 pv_url / selected_bgm_url / auto_fetch_bgm=True 也不保存、不下载）
                r_none = await client.post(
                    "/api/scraper/import",
                    json={
                        "title": "Mode None Game",
                        "pv_url": pv_remote,
                        "pv_mode": "none",
                        "selected_bgm_url": op_remote,
                        "auto_fetch_bgm": True,
                        "op_mode": "none",
                    },
                )
                self.assertEqual(r_none.status_code, 200, r_none.text)
                g_none = r_none.json()
                self.assertEqual(g_none["media"]["pv_mode"], "none")
                self.assertEqual(g_none["media"]["pv_url_or_path"], "")
                self.assertEqual(g_none["media"]["pv_remote_url"], "")
                self.assertEqual(g_none["media"]["bgm_mode"], "none")
                self.assertEqual(g_none["media"]["bgm_path"], "")
                self.assertEqual(g_none["media"]["bgm_remote_url"], "")
                await asyncio.sleep(0)
                pv_mock.assert_not_awaited()
                bgm_mock.assert_not_awaited()
                auto_bgm_mock.assert_not_awaited()

                # 2) mode = link_only（写入远程链接到 DB，绝不触发任何本地下载任务）
                r_link = await client.post(
                    "/api/scraper/import",
                    json={
                        "title": "Mode Link Only Game",
                        "pv_url": pv_remote,
                        "pv_mode": "link_only",
                        "selected_bgm_url": op_remote,
                        "op_mode": "link_only",
                        "auto_fetch_bgm": False,
                    },
                )
                self.assertEqual(r_link.status_code, 200, r_link.text)
                g_link = r_link.json()
                link_gid = g_link["id"]
                self.assertEqual(g_link["media"]["pv_mode"], "link_only")
                self.assertEqual(g_link["media"]["pv_remote_url"], pv_remote)
                self.assertEqual(g_link["media"]["pv_url_or_path"], pv_remote)
                self.assertEqual(g_link["media"]["bgm_mode"], "link_only")
                self.assertEqual(g_link["media"]["bgm_remote_url"], op_remote)
                self.assertEqual(g_link["media"]["bgm_path"], op_remote)
                await asyncio.sleep(0)
                pv_mock.assert_not_awaited()
                bgm_mock.assert_not_awaited()
                auto_bgm_mock.assert_not_awaited()
                self.assertIsNone(task_manager.get_task(link_gid, "pv"))
                self.assertIsNone(task_manager.get_task(link_gid, "bgm"))

                # 3) mode = download（先保留远程链接支持失败兜底，并立即派发后台下载任务）
                r_dl = await client.post(
                    "/api/scraper/import",
                    json={
                        "title": "Mode Download Game",
                        "pv_url": pv_remote,
                        "selected_pv_fallback_urls": [pv_fallback],
                        "pv_mode": "download",
                        "selected_bgm_url": op_remote,
                        "op_mode": "download",
                        "external_ids": {"steam": "123456"},
                    },
                )
                self.assertEqual(r_dl.status_code, 200, r_dl.text)
                g_dl = r_dl.json()
                dl_gid = g_dl["id"]
                self.assertEqual(g_dl["media"]["pv_mode"], "download")
                self.assertEqual(g_dl["media"]["pv_remote_url"], pv_remote)
                self.assertEqual(g_dl["media"]["pv_url_or_path"], pv_remote)
                self.assertEqual(g_dl["media"]["bgm_mode"], "download")
                self.assertEqual(g_dl["media"]["bgm_remote_url"], op_remote)
                self.assertEqual(g_dl["media"]["bgm_path"], op_remote)

                await asyncio.sleep(0.02)
                pv_mock.assert_awaited_once()
                pv_kwargs = pv_mock.await_args.kwargs
                self.assertEqual(pv_kwargs["game_id"], dl_gid)
                self.assertEqual(pv_kwargs["url"], pv_remote)
                self.assertEqual(pv_kwargs["fallback_urls"], [pv_fallback])
                self.assertEqual(pv_kwargs["steam_appid"], "123456")

                bgm_mock.assert_awaited_once()
                self.assertEqual(bgm_mock.await_args.args[0], dl_gid)
                self.assertEqual(bgm_mock.await_args.args[1], op_remote)

    async def test_drop_local_cache_and_cache_remote_bidirectional_conversion(self) -> None:
        pv_remote = "https://cdn.example.com/trailer_max.mp4"
        op_remote = "https://www.bilibili.com/video/BV1testOP"

        async with self.session_maker() as session:
            game = Game(title="Cache Switch Game")
            game.media = GameMediaPath(
                pv_url_or_path="assets/1/pv.mp4",
                pv_remote_url=pv_remote,
                pv_mode="download",
                bgm_path="assets/1/bgm.m4a",
                bgm_remote_url=op_remote,
                bgm_mode="download",
            )
            game.play_record = PlayRecord(total_seconds=0)
            session.add(game)
            await session.commit()
            gid = game.id

        # 在临时 assets 目录创建伪造的本地缓存文件
        gdir = self.assets_dir / str(gid)
        gdir.mkdir(parents=True, exist_ok=True)
        local_pv = gdir / "pv.mp4"
        local_bgm = gdir / "bgm.m4a"
        local_pv.write_bytes(b"LOCAL_PV_CONTENT")
        local_bgm.write_bytes(b"LOCAL_BGM_CONTENT")

        pv_mock = AsyncMock(return_value=None)
        bgm_mock = AsyncMock(return_value=None)

        with (
            patch.object(media_service, "DATA_DIR", self.tmp_root),
            patch.object(media_service, "ASSETS_DIR", self.assets_dir),
            patch.object(media_api, "DATA_DIR", self.tmp_root),
            patch.object(scraper_api, "_background_download_pv", new=pv_mock),
            patch.object(scraper_api, "_background_download_selected_bgm", new=bgm_mock),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                # 1) 本地缓存 -> 仅删除本地文件、保留在线链接（PV）
                r_drop_pv = await client.post(
                    f"/api/media/drop-local-cache/{gid}",
                    params={"asset_type": "pv"},
                )
                self.assertEqual(r_drop_pv.status_code, 200, r_drop_pv.text)
                body_pv = r_drop_pv.json()
                self.assertFalse(local_pv.exists(), "Local pv.mp4 should be removed")
                self.assertEqual(body_pv["media"]["pv_mode"], "link_only")
                self.assertEqual(body_pv["media"]["pv_remote_url"], pv_remote)
                self.assertEqual(body_pv["media"]["pv_url_or_path"], pv_remote)

                # 2) 本地缓存 -> 仅删除本地文件、保留在线链接（OP）
                r_drop_bgm = await client.post(
                    f"/api/media/drop-local-cache/{gid}",
                    params={"asset_type": "bgm"},
                )
                self.assertEqual(r_drop_bgm.status_code, 200, r_drop_bgm.text)
                body_bgm = r_drop_bgm.json()
                self.assertFalse(local_bgm.exists(), "Local bgm.m4a should be removed")
                self.assertEqual(body_bgm["media"]["bgm_mode"], "link_only")
                self.assertEqual(body_bgm["media"]["bgm_remote_url"], op_remote)
                self.assertEqual(body_bgm["media"]["bgm_path"], op_remote)

                # 3) 仅在线链接 -> 触发下载到本地（PV）
                r_cache_pv = await client.post(
                    f"/api/media/cache-remote/{gid}",
                    params={"asset_type": "pv"},
                )
                self.assertEqual(r_cache_pv.status_code, 200, r_cache_pv.text)
                cached_pv = r_cache_pv.json()
                self.assertEqual(cached_pv["media"]["pv_mode"], "download")
                self.assertIn("download_task", cached_pv)
                self.assertEqual(cached_pv["download_task"]["status"], "queued")
                await asyncio.sleep(0.02)
                pv_mock.assert_awaited_once()
                self.assertEqual(pv_mock.await_args.kwargs["url"], pv_remote)


if __name__ == "__main__":
    unittest.main()
