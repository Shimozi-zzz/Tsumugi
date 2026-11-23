from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
from pathlib import Path
import shutil
from typing import Any, Callable, Iterable, Literal
from urllib.parse import urlparse

import httpx
from PIL import Image
from pypinyin import Style, pinyin
import yt_dlp

from backend.core.config import ASSETS_DIR, DATA_DIR, THUMBS_CACHE_DIR
from backend.scrapers.bilibili import BILIBILI_REFERER, BILIBILI_USER_AGENT
from backend.services.task_manager import task_manager

logger = logging.getLogger("tsumugi.services.media_service")

WEBP_IMAGE_ASSET_TYPES = {"cover", "logo", "hero", "spine", "custom_spine"}
DIRECT_VIDEO_EXTS = {".mp4", ".webm"}
SAVED_VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}
SAVED_AUDIO_EXTS = {".m4a", ".mp3", ".ogg", ".wav", ".flac", ".webm", ".opus"}


class _SilentYdlLogger:
    def debug(self, _msg: str) -> None:
        pass

    def warning(self, _msg: str) -> None:
        pass

    def error(self, _msg: str) -> None:
        pass


_SILENT_YDL_LOGGER = _SilentYdlLogger()


class MediaDownloadError(RuntimeError):
    """封装已中文化的媒体下载异常，同时保留原始底层错误便于日志排查"""

    def __init__(self, zh_message: str, raw_error: str = "") -> None:
        super().__init__(zh_message)
        self.zh_message = zh_message
        self.raw_error = raw_error or zh_message


def format_download_error_zh(
    err: BaseException | str,
    *,
    media_kind: Literal["video", "audio"] = "video",
) -> str:
    """
    将 yt-dlp / httpx / ffmpeg / 网络底层英文异常映射为清晰克制的中文提示，
    绝不向前端裸露 `ERROR: [generic] ... Use --list-formats` 等英文命令行文本。
    """
    if isinstance(err, MediaDownloadError):
        return err.zh_message

    raw = str(err or "").strip()
    low = raw.lower()
    is_audio = media_kind == "audio"

    # 1. Requested format is not available（含 Steam hls_264_master 等场景）
    if (
        "requested format is not available" in low
        or "no video formats found" in low
        or "no audio formats found" in low
        or "format is not available" in low
    ):
        return (
            "该音频源暂无兼容的本地下载格式，已保留在线链接可直接播放，或稍后重试"
            if is_audio
            else "该视频源暂无兼容的本地下载格式，已保留在线链接可直接播放，或稍后重试"
        )

    # 2. 缺少 ffmpeg / ffprobe
    if (
        "ffmpeg" in low
        or "ffprobe" in low
        or ("postprocessing" in low and "not installed" in low)
        or "cannot merge" in low
    ):
        return (
            "未检测到 FFmpeg，无法转换或合并该音频流；当前已保留在线链接可直接播放"
            if is_audio
            else "未检测到 FFmpeg，无法合并该流媒体音视频；当前已保留在线链接可直接播放"
        )

    # 3. HTTP 403 / 412 风控或防盗链
    if (
        "http error 403" in low
        or "http error 412" in low
        or "403 forbidden" in low
        or "412 precondition" in low
        or "status code 403" in low
        or "status code 412" in low
        or "client error '403" in low
        or "client error '412" in low
        or (isinstance(err, httpx.HTTPStatusError) and err.response.status_code in (403, 412))
    ):
        return (
            "音频源拒绝访问（可能触发风控或防盗链），建议稍后重试或切换其他平台源"
            if is_audio
            else "视频源拒绝访问（可能触发风控或防盗链），建议稍后重试或切换其他平台源"
        )

    # 4. HTTP 404 / 410 链接失效
    if (
        "http error 404" in low
        or "http error 410" in low
        or "404 not found" in low
        or "410 gone" in low
        or "status code 404" in low
        or "status code 410" in low
        or "client error '404" in low
        or "client error '410" in low
        or "video unavailable" in low
        or (isinstance(err, httpx.HTTPStatusError) and err.response.status_code in (404, 410))
    ):
        return (
            "该音频链接已失效（404），请重新搜索并更换音频源"
            if is_audio
            else "该视频链接已失效（404），请重新搜索并更换视频源"
        )

    # 5. 超时 / 网络 / 代理异常
    if (
        isinstance(
            err,
            (
                TimeoutError,
                asyncio.TimeoutError,
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.ProxyError,
            ),
        )
        or "timed out" in low
        or "timeout" in low
        or "connection reset" in low
        or "connection refused" in low
        or "connection aborted" in low
        or "proxy" in low
        or "name or service not known" in low
        or "getaddrinfo failed" in low
        or "failed to establish a new connection" in low
        or ("ssl" in low and ("error" in low or "eof" in low or "certificate" in low))
        or ("unable to download" in low and ("network" in low or "urlopen" in low or "connection" in low))
    ):
        return (
            "连接音频源超时，请检查网络或代理设置后重试"
            if is_audio
            else "连接视频源超时，请检查网络或代理设置后重试"
        )

    # 6. Unsupported URL
    if "unsupported url" in low:
        return "暂不支持下载该平台链接，已保留在线链接供播放"

    # 7. 若本身已是干净中文提示且不含命令行/堆栈英文噪声，保留原文
    noise_markers = (
        "error:",
        "traceback",
        "exception",
        "yt-dlp",
        "http error",
        "--list-formats",
        "urlopen",
        "errno",
        "hls_264",
        "[generic]",
    )
    if (
        raw
        and len(raw) <= 80
        and any("\u4e00" <= ch <= "\u9fff" for ch in raw)
        and not any(m in low for m in noise_markers)
    ):
        return raw

    # 8. 其余未知异常统一友好兜底
    return (
        "本地音频下载失败，已保留在线链接可直接播放"
        if is_audio
        else "本地视频下载失败，已保留在线链接可直接播放"
    )


def generate_pinyin_initials(text: str) -> str:
    """提取中文字符串的拼音首字母（保留英文字母与数字以便混合检索）"""
    if not text:
        return ""

    initials = pinyin(text, style=Style.FIRST_LETTER, errors="default")
    raw = "".join(item[0].lower() for item in initials if item)
    return "".join(ch for ch in raw if ch.isalnum())


def convert_image_to_webp(content: bytes, asset_type: str = "cover") -> tuple[bytes, str]:
    """
    将图片字节流自动压缩为 WebP：
    - 动图 GIF 保留原格式（避免帧丢失或异常崩溃）
    - logo 保留完整 Alpha 透明通道（quality=90, method=4）
    - cover / hero / spine 正确处理 RGBA/RGB 色彩空间（quality=85, method=4）
    返回 (输出字节, 后缀名)
    """
    if not content:
        raise ValueError("图片内容为空")

    with Image.open(io.BytesIO(content)) as img:
        is_animated_gif = (
            (img.format or "").upper() == "GIF"
            and getattr(img, "is_animated", False)
            and getattr(img, "n_frames", 1) > 1
        )
        if is_animated_gif:
            return content, ".gif"

        normalized_type = "custom_spine" if asset_type == "spine" else asset_type
        out = io.BytesIO()

        if normalized_type == "logo":
            converted = img.convert("RGBA")
            converted.save(out, format="WEBP", quality=90, method=4)
        else:
            has_alpha = img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            )
            converted = img.convert("RGBA" if has_alpha else "RGB")
            converted.save(out, format="WEBP", quality=85, method=4)

        return out.getvalue(), ".webp"


def generate_cover_thumbnail(
    source_file: Path,
    game_dir: Path,
    max_width: int = 420,
    quality: int = 80,
) -> str:
    """为封面生成/更新轻量 WebP 缩略图（最大宽度 420px，quality=80），返回 data/ 相对路径"""
    thumb_file = game_dir / "cover_thumb.webp"
    with Image.open(source_file) as img:
        has_alpha = img.mode in ("RGBA", "LA") or (
            img.mode == "P" and "transparency" in img.info
        )
        prepared = img.convert("RGBA" if has_alpha else "RGB")
        if prepared.width > max_width:
            ratio = max_width / max(prepared.width, 1)
            new_size = (max_width, max(int(prepared.height * ratio), 1))
            prepared = prepared.resize(new_size, Image.Resampling.LANCZOS)
        prepared.save(thumb_file, format="WEBP", quality=quality, method=4)
    return thumb_file.relative_to(DATA_DIR).as_posix()


def save_game_asset_bytes(
    game_id: int,
    asset_type: str,
    filename: str,
    content: bytes,
) -> dict[str, str]:
    """
    将上传或下载的视觉资产保存到 data/assets/{game_id}/ 目录：
    - cover / hero / spine / logo 自动转为 WebP 瘦身落盘（动图 GIF 保留原格式）；
    - 保存封面（cover）时，自动同步生成/更新 420px 宽 WebP 缩略图供回廊与侧边栏高速渲染。
    """
    game_dir = ASSETS_DIR / str(game_id)
    game_dir.mkdir(parents=True, exist_ok=True)

    storage_type = "custom_spine" if asset_type == "spine" else asset_type
    final_content = content
    ext = Path(filename).suffix.lower() or ".png"

    if storage_type in WEBP_IMAGE_ASSET_TYPES:
        final_content, ext = convert_image_to_webp(content, storage_type)

    # 清理同类型旧后缀文件，避免目录中同时残留 cover.jpg 和 cover.webp
    for old_file in game_dir.glob(f"{storage_type}.*"):
        if old_file.name != f"{storage_type}_thumb.webp" and old_file.is_file():
            try:
                old_file.unlink()
            except OSError:
                pass

    target_file = game_dir / f"{storage_type}{ext}"
    target_file.write_bytes(final_content)

    rel_path = target_file.relative_to(DATA_DIR).as_posix()
    result = {"path": rel_path}

    if storage_type == "cover":
        result["thumb_path"] = generate_cover_thumbnail(target_file, game_dir)

    return result


def get_or_create_thumbnail(raw_path: str, width: int = 360) -> Path:
    """
    按需生成 WebP 缩略图并缓存至 data/cache/thumbs/。
    支持传入 data/ 下的相对路径，也支持本地截图文件夹的绝对路径。
    """
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = DATA_DIR / candidate

    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"目标图片不存在: {raw_path}")

    THUMBS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    mtime = candidate.stat().st_mtime
    cache_key = hashlib.sha256(
        f"{candidate.resolve()}:{mtime}:{width}".encode("utf-8")
    ).hexdigest()
    cached_thumb = THUMBS_CACHE_DIR / f"{cache_key}.webp"

    if not cached_thumb.exists():
        with Image.open(candidate) as img:
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
            else:
                img = img.convert("RGB")
            if img.width > width:
                ratio = width / img.width
                new_height = max(int(img.height * ratio), 1)
                img = img.resize((width, new_height), Image.Resampling.LANCZOS)
            img.save(cached_thumb, format="WEBP", quality=85)

    return cached_thumb


# ──────────────────── PV / OP 本地缓存下载与释放（直链优先 + HLS 兼容 + 中文报错） ────────────────────


def is_remote_http_url(raw: str | None) -> bool:
    s = (raw or "").strip().lower()
    return s.startswith(("http://", "https://"))


def direct_video_extension(url: str, mime_hint: str = "") -> str:
    """若为直链 .mp4 或 .webm 则返回对应后缀，否则返回空字符串交由 yt-dlp（支持 .m3u8/.mpd/网页）"""
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in DIRECT_VIDEO_EXTS:
        return suffix
    hint = (mime_hint or "").strip().lower()
    if hint == "mp4" and suffix not in (".m3u8", ".mpd"):
        return ".mp4"
    if hint == "webm" and suffix not in (".m3u8", ".mpd"):
        return ".webm"
    return ""


def cleanup_pv_temp_files(game_dir: Path) -> None:
    if not game_dir.exists():
        return
    for temp in game_dir.glob("pv.downloading*"):
        if temp.is_file():
            try:
                temp.unlink()
            except OSError:
                pass


def cleanup_legacy_pv_files(game_dir: Path, keep_name: str = "pv.mp4") -> None:
    if not game_dir.exists():
        return
    for old in game_dir.glob("pv.*"):
        if old.is_file() and old.name != keep_name:
            try:
                old.unlink()
            except OSError:
                pass


def delete_local_media_cache(game_id: int, asset_type: Literal["pv", "bgm"]) -> int:
    """仅删除 data/assets/{game_id}/ 下对应的本地缓存视频或音频文件，返回删除数量"""
    game_dir = ASSETS_DIR / str(game_id)
    if not game_dir.exists() or not game_dir.is_dir():
        return 0
    prefix = "pv" if asset_type == "pv" else "bgm"
    removed = 0
    for f in list(game_dir.glob(f"{prefix}.*")):
        if f.is_file():
            try:
                f.unlink()
                removed += 1
            except OSError as exc:
                logger.warning("Failed deleting local %s cache %s: %s", prefix, f, exc)
    return removed


def build_ytdlp_pv_options(
    game_dir: Path,
    *,
    url: str,
    has_ffmpeg: bool,
    proxy_url: str = "",
    format_override: str | None = None,
    progress_hook: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """
    构造对 Steam HLS（.m3u8）与通用视频站高度兼容的 yt-dlp 参数：
    - 移除硬编码限制输入流扩展名的 [ext=mp4]；
    - 有 ffmpeg：bestvideo*+bestaudio/best + merge_output_format='mp4'；
    - 无 ffmpeg：best[vcodec!=none][acodec!=none]/best。
    """
    if format_override:
        fmt = format_override
    elif has_ffmpeg:
        fmt = "bestvideo*+bestaudio/best"
    else:
        fmt = "best[vcodec!=none][acodec!=none]/best"

    opts: dict[str, Any] = {
        "format": fmt,
        "outtmpl": str(game_dir / "pv.downloading.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "logger": _SILENT_YDL_LOGGER,
        "socket_timeout": 20,
        "retries": 1,
        "overwrites": True,
        "nopart": True,
    }
    if progress_hook is not None:
        opts["progress_hooks"] = [progress_hook]
    if has_ffmpeg:
        opts["merge_output_format"] = "mp4"
    if proxy_url:
        opts["proxy"] = proxy_url
    if "bilibili.com" in url.lower():
        opts["http_headers"] = {
            "Referer": BILIBILI_REFERER,
            "User-Agent": BILIBILI_USER_AGENT,
        }
    return opts


async def _download_direct_video_stream(
    game_id: int,
    url: str,
    game_dir: Path,
    proxy_url: str,
    ext: str = ".mp4",
) -> Path:
    """对直链 .mp4 / .webm 使用 httpx 流式下载写入 pv.downloading.{ext}（无需 yt-dlp/ffmpeg）"""
    tmp_path = game_dir / f"pv.downloading{ext}"
    cleanup_pv_temp_files(game_dir)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
    }

    async with httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(20.0, read=120.0),
        follow_redirects=True,
        proxy=(proxy_url.strip() or None),
    ) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            total_raw = resp.headers.get("content-length")
            total_bytes = int(total_raw) if (total_raw and total_raw.isdigit()) else 0
            downloaded = 0
            last_pct = -1

            with tmp_path.open("wb") as fp:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    if not chunk:
                        continue
                    fp.write(chunk)
                    downloaded += len(chunk)
                    if total_bytes > 0:
                        pct = min(99, int(downloaded * 100 / total_bytes))
                        if pct != last_pct:
                            last_pct = pct
                            task_manager.update_progress(game_id, "pv", pct, "正在下载宣传片…")

    if not tmp_path.exists() or tmp_path.stat().st_size == 0:
        cleanup_pv_temp_files(game_dir)
        raise RuntimeError("下载到的宣传片视频文件为空")

    return tmp_path


def _locate_downloaded_pv_temp(game_dir: Path) -> Path:
    for candidate in sorted(game_dir.glob("pv.downloading.*")):
        if (
            candidate.is_file()
            and candidate.suffix.lower() in SAVED_VIDEO_EXTS
            and candidate.stat().st_size > 0
        ):
            return candidate
    for candidate in sorted(game_dir.glob("pv.downloading.*")):
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    raise FileNotFoundError("未能定位下载后的宣传片临时文件")


def _download_pv_with_ytdlp_sync(
    game_id: int,
    url: str,
    game_dir: Path,
    proxy_url: str,
) -> Path:
    """
    使用 yt-dlp 下载宣传片（支持 HLS .m3u8 / Bilibili / YouTube）：
    - 动态检测 ffmpeg；
    - 首次遇到 `Requested format is not available` 时自动放宽为 `b/bv*+ba/best` 重试一次。
    """
    cleanup_pv_temp_files(game_dir)
    has_ffmpeg = bool(shutil.which("ffmpeg"))

    def _progress_hook(d: dict[str, Any]) -> None:
        st = d.get("status")
        if st == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if total and total > 0:
                pct = min(99, int(done * 100 / total))
                task_manager.update_progress(game_id, "pv", pct, "正在下载宣传片…")
            else:
                frag_idx = d.get("fragment_index")
                frag_cnt = d.get("fragment_count")
                if frag_idx and frag_cnt:
                    pct = min(99, int(frag_idx * 100 / frag_cnt))
                    task_manager.update_progress(game_id, "pv", pct, "正在下载宣传片分片…")
        elif st == "finished":
            task_manager.update_progress(game_id, "pv", 99, "正在封装本地视频…")

    def _run_once(format_override: str | None = None) -> Path:
        ydl_opts = build_ytdlp_pv_options(
            game_dir,
            url=url,
            has_ffmpeg=has_ffmpeg,
            proxy_url=proxy_url,
            format_override=format_override,
            progress_hook=_progress_hook,
        )
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise RuntimeError("yt-dlp 未返回有效视频信息")
        return _locate_downloaded_pv_temp(game_dir)

    try:
        return _run_once(format_override=None)
    except Exception as exc:
        if "requested format is not available" in str(exc).lower():
            logger.warning(
                "yt-dlp format unavailable for game_id=%s url=%s (%s); retrying with relaxed format b/bv*+ba/best",
                game_id,
                url,
                exc,
            )
            cleanup_pv_temp_files(game_dir)
            task_manager.update_progress(game_id, "pv", 5, "正在切换兼容格式重试下载…")
            return _run_once(format_override="b/bv*+ba/best")
        raise


def _pick_direct_fallback_urls(fallback_urls: Iterable[str] | None, skip_url: str = "") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen = {skip_url.strip()}
    for raw in fallback_urls or []:
        u = str(raw or "").strip()
        if not u or u in seen or not is_remote_http_url(u):
            continue
        ext = direct_video_extension(u)
        if ext:
            seen.add(u)
            out.append((u, ext))
    return out


async def download_pv_to_local(
    game_id: int,
    url: str,
    proxy_url: str = "",
    mime_hint: str = "",
    fallback_urls: Iterable[str] | None = None,
) -> str:
    """
    本地化下载宣传片 PV 至 data/assets/{game_id}/pv.{ext}（先写临时文件再原子重命名）：
    - 命中直链 .mp4 / .webm：直接通过 httpx 流式下载（绕过 yt-dlp 与 ffmpeg）；
    - HLS (.m3u8) / Bilibili / YouTube：通过 yt-dlp 下载，首次格式不可用自动降级 `b/bv*+ba/best` 重试；
    - 若 yt-dlp 仍失败且存在 Steam 备用直链 .mp4/.webm，自动回退直链流式下载；
    - 失败时完整原始错误写入日志，面向前端统一映射为中文提示。
    """
    cleaned = (url or "").strip()
    if not is_remote_http_url(cleaned):
        msg = "无效的视频链接"
        task_manager.mark_error(game_id, "pv", msg)
        raise MediaDownloadError(msg)

    game_dir = ASSETS_DIR / str(game_id)
    game_dir.mkdir(parents=True, exist_ok=True)
    direct_ext = direct_video_extension(cleaned, mime_hint)
    final_ext = direct_ext if direct_ext else ".mp4"
    final_path = game_dir / f"pv{final_ext}"
    direct_fallbacks = _pick_direct_fallback_urls(fallback_urls, skip_url=cleaned)

    task_manager.set_task(game_id, "pv", "downloading", 0, "正在下载宣传片…")
    try:
        tmp_file: Path | None = None
        last_exc: Exception | None = None

        if direct_ext:
            try:
                tmp_file = await _download_direct_video_stream(
                    game_id, cleaned, game_dir, proxy_url, ext=direct_ext
                )
            except Exception as exc:
                last_exc = exc
                logger.warning("Direct PV stream failed for game_id=%s url=%s: %s", game_id, cleaned, exc)
        else:
            try:
                tmp_file = await asyncio.wait_for(
                    asyncio.to_thread(_download_pv_with_ytdlp_sync, game_id, cleaned, game_dir, proxy_url),
                    timeout=180.0,
                )
            except Exception as exc:
                last_exc = exc
                logger.warning("yt-dlp PV download failed for game_id=%s url=%s: %s", game_id, cleaned, exc)

        # 若主链接失败且存在备用直链 mp4/webm（如 Steam 备用直链），自动回退直链下载
        if tmp_file is None and direct_fallbacks:
            for fb_url, fb_ext in direct_fallbacks:
                try:
                    logger.info("Falling back to direct PV stream for game_id=%s url=%s", game_id, fb_url)
                    task_manager.update_progress(game_id, "pv", 10, "正在尝试备用直链下载…")
                    tmp_file = await _download_direct_video_stream(
                        game_id, fb_url, game_dir, proxy_url, ext=fb_ext
                    )
                    final_path = game_dir / f"pv{fb_ext}"
                    break
                except Exception as fb_exc:
                    last_exc = fb_exc
                    logger.warning("Fallback direct PV stream failed for %s: %s", fb_url, fb_exc)

        if tmp_file is None:
            raise last_exc or RuntimeError("本地视频下载失败")

        if tmp_file.suffix.lower() in (".mp4", ".webm"):
            final_path = game_dir / f"pv{tmp_file.suffix.lower()}"

        os.replace(tmp_file, final_path)
        cleanup_pv_temp_files(game_dir)
        cleanup_legacy_pv_files(game_dir, keep_name=final_path.name)

        rel_path = final_path.relative_to(DATA_DIR).as_posix()
        task_manager.mark_done(game_id, "pv", "宣传片已缓存到本地")
        return rel_path
    except Exception as exc:
        cleanup_pv_temp_files(game_dir)
        logger.error("PV download failed for game_id=%s url=%s: %s", game_id, cleaned, exc, exc_info=True)
        zh_msg = format_download_error_zh(exc, media_kind="video")
        task_manager.mark_error(game_id, "pv", zh_msg)
        raise MediaDownloadError(zh_msg, raw_error=str(exc)) from exc


def _extract_remote_video_stream_sync(url: str, proxy_url: str) -> tuple[str, dict[str, str]]:
    """为 Bilibili / YouTube 等网页链接解析可直接流播的单文件音视频直链（供仅保留链接模式在线播放）"""
    ydl_opts: dict[str, Any] = {
        "format": "best[vcodec!=none][acodec!=none]/b/best",
        "quiet": True,
        "no_warnings": True,
        "logger": _SILENT_YDL_LOGGER,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 12,
    }
    if proxy_url:
        ydl_opts["proxy"] = proxy_url
    if "bilibili.com" in url.lower():
        ydl_opts["http_headers"] = {
            "Referer": BILIBILI_REFERER,
            "User-Agent": BILIBILI_USER_AGENT,
        }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if not isinstance(info, dict):
            raise RuntimeError("未能解析在线视频流")
        stream_url = str(info.get("url") or "").strip()
        if not stream_url:
            raise RuntimeError("未找到可用的在线视频直链")
        headers = info.get("http_headers") if isinstance(info.get("http_headers"), dict) else {}
        return stream_url, {str(k): str(v) for k, v in headers.items()}


async def resolve_remote_video_stream(url: str, proxy_url: str = "") -> tuple[str, dict[str, str]]:
    cleaned = (url or "").strip()
    if direct_video_extension(cleaned):
        return cleaned, {}
    return await asyncio.wait_for(
        asyncio.to_thread(_extract_remote_video_stream_sync, cleaned, proxy_url),
        timeout=15.0,
    )
