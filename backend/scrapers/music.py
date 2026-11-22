import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yt_dlp

from backend.core.config import ASSETS_DIR, DATA_DIR
from backend.scrapers.bilibili import (
    BILIBILI_REFERER,
    BILIBILI_USER_AGENT,
    search_bilibili_videos,
)

logger = logging.getLogger("tsumugi.scrapers.music")


class _SilentYdlLogger:
    def debug(self, _msg: str) -> None:
        pass

    def warning(self, _msg: str) -> None:
        pass

    def error(self, _msg: str) -> None:
        pass


_SILENT_YDL_LOGGER = _SilentYdlLogger()

DIRECT_AUDIO_EXTS = {".m4a", ".mp3", ".ogg", ".wav", ".flac", ".webm", ".opus"}
MIN_DURATION_SEC = 60
MAX_DURATION_SEC = 420
SEARCH_TIMEOUT_SEC = 10.0


def _make_candidate_id(source: str, raw_id: str) -> str:
    digest = hashlib.sha1(f"{source}:{raw_id}".encode("utf-8")).hexdigest()[:12]
    return f"{source.lower()}-{digest}"


def _ytdlp_search_sync(prefix: str, query: str, source_label: str, proxy_url: str) -> list[dict[str, Any]]:
    """在独立线程中调用 yt-dlp 扁平检索（避免阻塞 FastAPI 事件循环）"""
    search_expr = f"{prefix}:{query}"
    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "logger": _SILENT_YDL_LOGGER,
        "extract_flat": True,
        "skip_download": True,
        "socket_timeout": 7,
        "retries": 0,
        "ignoreerrors": True,
    }
    if proxy_url:
        ydl_opts["proxy"] = proxy_url

    results: list[dict[str, Any]] = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_expr, download=False)
    except Exception as exc:
        logger.debug("[%s] yt-dlp search failed for %r: %s", source_label, query, exc)
        return []

    if not isinstance(info, dict):
        return []

    entries = info.get("entries") or []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        dur = entry.get("duration")
        if dur is not None:
            try:
                dur_int = int(round(float(dur)))
            except (TypeError, ValueError):
                dur_int = 0
            if dur_int > 0 and not (MIN_DURATION_SEC <= dur_int <= MAX_DURATION_SEC):
                continue
        else:
            dur_int = 0

        raw_url = str(entry.get("webpage_url") or entry.get("url") or "").strip()
        raw_id = str(entry.get("id") or raw_url)
        if not raw_url:
            continue
        if source_label == "YouTube" and not raw_url.startswith("http"):
            raw_url = f"https://www.youtube.com/watch?v={raw_url}"
        elif source_label == "Bilibili" and not raw_url.startswith("http"):
            raw_url = f"https://www.bilibili.com/video/{raw_url}"

        title = str(entry.get("title") or "").strip()
        if not title:
            continue

        thumb = str(entry.get("thumbnail") or "")
        if not thumb and isinstance(entry.get("thumbnails"), list) and entry["thumbnails"]:
            first_t = entry["thumbnails"][0]
            if isinstance(first_t, dict):
                thumb = str(first_t.get("url") or "")

        results.append(
            {
                "id": _make_candidate_id(source_label, raw_id),
                "title": title,
                "artist": str(entry.get("uploader") or entry.get("channel") or source_label),
                "source": source_label,
                "duration": dur_int,
                "thumbnail": thumb,
                "preview_url": "",
                "source_url": raw_url,
            }
        )
        if len(results) >= 5:
            break

    return results


async def _search_bilibili_op(
    query: str,
    proxy_url: str,
    game_titles: list[str] | None = None,
) -> list[dict[str, Any]]:
    """通过真实 Bilibili WBI 接口搜索游戏 OP/主题曲候选（带相关性过滤与加权排序）"""
    cleaned = query.strip()
    if not cleaned:
        return []
    titles = [t for t in (game_titles or [cleaned]) if t and t.strip()]

    merged: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for suffix in ("OP", "主题曲"):
        raw_items = await search_bilibili_videos(
            f"{cleaned} {suffix}",
            page_size=8,
            min_duration=MIN_DURATION_SEC,
            max_duration=MAX_DURATION_SEC,
            proxy_url=proxy_url,
            game_titles=titles,
            kind="op",
        )
        for it in raw_items:
            if it["url"] in seen_urls:
                continue
            seen_urls.add(it["url"])
            merged.append(
                {
                    "id": it["id"],
                    "title": it["title"],
                    "artist": it["author"] or "Bilibili",
                    "source": "Bilibili",
                    "duration": it["duration"],
                    "thumbnail": it["thumbnail"],
                    "preview_url": "",
                    "source_url": it["url"],
                }
            )
            if len(merged) >= 6:
                return merged
        if len(merged) >= 4:
            break
    return merged[:6]


async def _search_youtube_op(query: str, proxy_url: str) -> list[dict[str, Any]]:
    search_term = f"{query.strip()} OP"
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_ytdlp_search_sync, "ytsearch8", search_term, "YouTube", proxy_url),
            timeout=SEARCH_TIMEOUT_SEC,
        )
    except Exception as exc:
        logger.debug("[YouTube] search timeout/error: %s", exc)
        return []


async def _search_bilibili_or_youtube(
    query: str,
    proxy_url: str,
    game_titles: list[str] | None = None,
) -> list[dict[str, Any]]:
    bili_res, yt_res = await asyncio.gather(
        _search_bilibili_op(query, proxy_url, game_titles=game_titles),
        _search_youtube_op(query, proxy_url),
        return_exceptions=True,
    )

    merged: list[dict[str, Any]] = []
    # 置顶 Bilibili 候选，其次 YouTube
    if isinstance(bili_res, list):
        merged.extend(bili_res)
    if isinstance(yt_res, list):
        merged.extend(yt_res)
    return merged[:6]


async def _search_itunes_jp(query: str, proxy_url: str) -> list[dict[str, Any]]:
    """iTunes JP Search API 极速兜底源（返回官方 30 秒 .m4a 试听直链）"""
    url = "https://itunes.apple.com/search"
    params = {
        "term": query.strip(),
        "country": "jp",
        "media": "music",
        "limit": 3,
    }
    try:
        async with httpx.AsyncClient(
            timeout=6.0,
            proxy=proxy_url or None,
            follow_redirects=True,
        ) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception as exc:
        logger.debug("[iTunes] search failed for %r: %s", query, exc)
        return []

    items: list[dict[str, Any]] = []
    for row in data.get("results") or []:
        if not isinstance(row, dict):
            continue
        preview = str(row.get("previewUrl") or "").strip()
        if not preview:
            continue
        track_id = str(row.get("trackId") or preview)
        ms = row.get("trackTimeMillis") or 0
        try:
            dur = max(0, int(round(int(ms) / 1000)))
        except (TypeError, ValueError):
            dur = 30
        thumb = str(row.get("artworkUrl100") or row.get("artworkUrl60") or "")
        items.append(
            {
                "id": _make_candidate_id("iTunes", track_id),
                "title": str(row.get("trackName") or row.get("collectionName") or query).strip(),
                "artist": str(row.get("artistName") or "iTunes JP").strip(),
                "source": "iTunes",
                "duration": dur,
                "thumbnail": thumb,
                "preview_url": preview,
                "source_url": str(row.get("trackViewUrl") or preview),
            }
        )
    return items


async def search_op_music(
    query: str,
    proxy_url: str = "",
    source: str = "auto",
    alt_title: str = "",
) -> list[dict[str, Any]]:
    """支持多平台分选（auto / bilibili / youtube / itunes）检索 OP/主题曲，单源失败静默降级"""
    cleaned = (query or "").strip()
    if not cleaned:
        return []

    norm_src = (source or "auto").strip().lower()
    titles = [t for t in (cleaned, (alt_title or "").strip()) if t]

    if norm_src == "bilibili":
        return await _search_bilibili_op(cleaned, proxy_url, game_titles=titles)
    if norm_src == "youtube":
        return await _search_youtube_op(cleaned, proxy_url)
    if norm_src in ("itunes", "music"):
        return await _search_itunes_jp(cleaned, proxy_url)

    full_res, itunes_res = await asyncio.gather(
        _search_bilibili_or_youtube(cleaned, proxy_url, game_titles=titles),
        _search_itunes_jp(cleaned, proxy_url),
        return_exceptions=True,
    )

    combined: list[dict[str, Any]] = []
    if isinstance(full_res, list):
        combined.extend(full_res)
    if isinstance(itunes_res, list):
        combined.extend(itunes_res)
    return combined


def _cleanup_old_bgm(game_dir: Path) -> None:
    for old in game_dir.glob("bgm.*"):
        if old.is_file():
            try:
                old.unlink()
            except OSError:
                pass


def _is_direct_audio_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    return ext in DIRECT_AUDIO_EXTS


async def _download_direct_audio(
    url: str,
    game_dir: Path,
    proxy_url: str,
) -> Path:
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    if ext not in DIRECT_AUDIO_EXTS:
        ext = ".m4a"
    async with httpx.AsyncClient(
        timeout=20.0,
        proxy=proxy_url or None,
        follow_redirects=True,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content = resp.content
        if not content:
            raise ValueError("下载到的音频内容为空")

    _cleanup_old_bgm(game_dir)
    out_file = game_dir / f"bgm{ext}"
    out_file.write_bytes(content)
    return out_file


def _download_with_ytdlp_sync(url: str, game_dir: Path, proxy_url: str) -> Path:
    """使用 yt-dlp 直接下载浏览器可播原生音频流（bestaudio[ext=m4a]/bestaudio），不依赖 ffmpeg"""
    _cleanup_old_bgm(game_dir)
    ydl_opts: dict[str, Any] = {
        "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
        "outtmpl": str(game_dir / "bgm.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "logger": _SILENT_YDL_LOGGER,
        "socket_timeout": 15,
        "retries": 1,
        "overwrites": True,
        "nopart": True,
    }
    if proxy_url:
        ydl_opts["proxy"] = proxy_url
    if "bilibili.com" in url.lower():
        ydl_opts["http_headers"] = {
            "Referer": BILIBILI_REFERER,
            "User-Agent": BILIBILI_USER_AGENT,
        }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            raise RuntimeError("yt-dlp 未返回有效媒体信息")

    for candidate in sorted(game_dir.glob("bgm.*")):
        if candidate.is_file() and candidate.suffix.lower() in DIRECT_AUDIO_EXTS:
            return candidate

    # 兜底：若下载后缀不在标准集合中仍返回实际生成文件
    for candidate in sorted(game_dir.glob("bgm.*")):
        if candidate.is_file():
            return candidate

    raise FileNotFoundError("未能定位下载后的原声音频文件")


async def download_op_music(
    game_id: int,
    source_url: str = "",
    preview_url: str = "",
    proxy_url: str = "",
) -> str:
    """异步下载并落盘至 data/assets/{game_id}/bgm.{ext}，返回 data/ 相对路径"""
    game_dir = ASSETS_DIR / str(game_id)
    game_dir.mkdir(parents=True, exist_ok=True)

    src = (source_url or "").strip()
    prev = (preview_url or "").strip()

    saved_file: Path | None = None
    last_error: Exception | None = None

    if src and _is_direct_audio_url(src):
        try:
            saved_file = await _download_direct_audio(src, game_dir, proxy_url)
        except Exception as exc:
            last_error = exc
    elif src:
        try:
            saved_file = await asyncio.wait_for(
                asyncio.to_thread(_download_with_ytdlp_sync, src, game_dir, proxy_url),
                timeout=60.0,
            )
        except Exception as exc:
            last_error = exc

    if saved_file is None and prev:
        try:
            saved_file = await _download_direct_audio(prev, game_dir, proxy_url)
        except Exception as exc:
            last_error = exc

    if saved_file is None:
        raise RuntimeError(f"原声下载失败: {last_error or '无可用音频地址'}")

    return saved_file.relative_to(DATA_DIR).as_posix()


def _extract_stream_url_sync(url: str, proxy_url: str) -> tuple[str, dict[str, str]]:
    """为 Bilibili / YouTube 候选项解析可试听的直链音频流地址"""
    ydl_opts: dict[str, Any] = {
        "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
        "quiet": True,
        "no_warnings": True,
        "logger": _SILENT_YDL_LOGGER,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 10,
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
            raise RuntimeError("未能解析音频流")
        stream_url = str(info.get("url") or "").strip()
        if not stream_url:
            raise RuntimeError("未找到可用的音频直链")
        headers = info.get("http_headers") if isinstance(info.get("http_headers"), dict) else {}
        return stream_url, {str(k): str(v) for k, v in headers.items()}


async def resolve_preview_stream(url: str, proxy_url: str = "") -> tuple[str, dict[str, str]]:
    cleaned = (url or "").strip()
    if _is_direct_audio_url(cleaned):
        return cleaned, {}
    return await asyncio.wait_for(
        asyncio.to_thread(_extract_stream_url_sync, cleaned, proxy_url),
        timeout=12.0,
    )
