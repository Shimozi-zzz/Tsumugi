import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx

from backend.core.config import ASSETS_DIR, DATA_DIR
from backend.services.media_service import save_game_asset_bytes

logger = logging.getLogger("tsumugi.services.asset_downloader")

CONTENT_TYPE_EXT_MAP = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}


def _guess_extension(url: str, content_type: str | None, default: str = ".png") -> str:
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct in CONTENT_TYPE_EXT_MAP:
            return CONTENT_TYPE_EXT_MAP[ct]
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".mp4", ".webm"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return default


async def _fetch_bytes(client: httpx.AsyncClient, url: str) -> tuple[bytes, str] | None:
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        if not resp.content:
            return None
        ext = _guess_extension(url, resp.headers.get("content-type"))
        return resp.content, ext
    except Exception as exc:
        logger.warning("Failed to download asset %s: %s", url, exc)
        return None


def _build_asset_headers(url: str) -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    host = (urlparse(url).hostname or "").lower()
    if "hdslb.com" in host or "bilibili.com" in host:
        headers["Referer"] = "https://www.bilibili.com/"
    elif "bgm.tv" in host:
        headers["Referer"] = "https://bgm.tv/"
    elif "touchgal" in host:
        headers["Referer"] = "https://www.touchgal.io/"
    elif "vndb.org" in host:
        headers["Referer"] = "https://vndb.org/"
    elif "dlsite.com" in host or "dlsite.jp" in host:
        headers["Referer"] = "https://www.dlsite.com/"
    elif "ymgal" in host:
        headers["Referer"] = "https://www.ymgal.games/"
    elif "kungal" in host:
        headers["Referer"] = "https://www.kungal.com/"
    elif "igdb.com" in host:
        headers["Referer"] = "https://www.igdb.com/"
    return headers


async def download_single_image_asset(
    game_id: int,
    asset_type: str,
    url: str,
    proxy_url: str = "",
) -> dict[str, str]:
    """
    下载单张远程视觉资产并落盘至 data/assets/{game_id}/：
    - asset_type: 'cover' | 'logo' | 'hero' | 'custom_spine'
    - 当 asset_type == 'cover' 时，自动生成 420px WebP 缩略图
    """
    cleaned_url = (url or "").strip()
    if not cleaned_url.startswith(("http://", "https://")):
        raise ValueError("无效的图片链接地址")

    storage_type = "custom_spine" if asset_type == "spine" else asset_type
    if storage_type not in {"cover", "logo", "hero", "custom_spine"}:
        raise ValueError(f"不支持的图片资产类型: {asset_type}")

    async with httpx.AsyncClient(
        headers=_build_asset_headers(cleaned_url),
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
        proxy=(proxy_url.strip() or None),
    ) as client:
        resp = await client.get(cleaned_url)
        resp.raise_for_status()
        content = resp.content
        if not content:
            raise ValueError("下载到的图片内容为空")
        content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        if content_type and not content_type.startswith("image/") and content_type != "application/octet-stream":
            raise ValueError(f"目标链接未返回图片内容 ({content_type})")
        ext = _guess_extension(cleaned_url, content_type, default=".png")

    return save_game_asset_bytes(
        game_id=game_id,
        asset_type=storage_type,
        filename=f"{storage_type}{ext}",
        content=content,
    )


async def download_game_assets(
    game_id: int,
    cover_url: str = "",
    logo_url: str = "",
    hero_bg_url: str = "",
    pv_url: str = "",
    screenshots: list[str] | None = None,
    proxy_url: str = "",
    skip_types: set[str] | None = None,
    download_screenshots: bool = True,
    max_screenshots: int = 8,
) -> dict[str, str]:
    """
    并发下载游戏远程视觉资产至 data/assets/{game_id}/，
    自动生成封面 420px WebP 缩略图，返回所有成功落盘的正斜杠相对路径字典。
    """
    skip = skip_types or set()
    result: dict[str, str] = {}

    headers = {
        "User-Agent": "TsumugiGameLibrary/0.3 (https://github.com/tsumugi-local)",
        "Accept": "*/*",
    }

    async with httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
        proxy=(proxy_url.strip() or None),
    ) as client:
        asset_jobs: list[tuple[str, str]] = []
        if cover_url and "cover" not in skip:
            asset_jobs.append(("cover", cover_url))
        if logo_url and "logo" not in skip:
            asset_jobs.append(("logo", logo_url))
        if hero_bg_url and "hero" not in skip:
            asset_jobs.append(("hero", hero_bg_url))

        async def _download_and_save(asset_type: str, url: str) -> None:
            fetched = await _fetch_bytes(client, url)
            if not fetched:
                return
            content, ext = fetched
            try:
                saved = save_game_asset_bytes(
                    game_id=game_id,
                    asset_type=asset_type,
                    filename=f"{asset_type}{ext}",
                    content=content,
                )
            except Exception as exc:
                logger.warning("Failed to persist %s for game %s: %s", asset_type, game_id, exc)
                return

            if asset_type == "cover":
                result["cover_path"] = saved["path"]
                if saved.get("thumb_path"):
                    result["cover_thumb_path"] = saved["thumb_path"]
            elif asset_type == "logo":
                result["logo_path"] = saved["path"]
            elif asset_type == "hero":
                result["hero_bg_path"] = saved["path"]

        # 处理宣传片 PV：HLS 流媒体 (.m3u8) 保留流链接直连播放；直链视频保留链接避免导入阻塞
        if pv_url and "pv" not in skip:
            result["pv_url_or_path"] = pv_url.strip()

        # 并发下载封面、Logo、Hero
        coros = [_download_and_save(atype, u) for atype, u in asset_jobs]

        # 可选并发下载部分预览 CG/截图到 data/assets/{game_id}/screenshots/
        ss_urls = [u for u in (screenshots or []) if u][:max_screenshots]
        if download_screenshots and ss_urls and "screenshots" not in skip:
            ss_dir = ASSETS_DIR / str(game_id) / "screenshots"
            ss_dir.mkdir(parents=True, exist_ok=True)

            async def _download_ss(idx: int, url: str) -> bool:
                fetched = await _fetch_bytes(client, url)
                if not fetched:
                    return False
                content, ext = fetched
                target = ss_dir / f"cg_{idx + 1:02d}{ext}"
                try:
                    target.write_bytes(content)
                    return True
                except OSError as exc:
                    logger.warning("Failed writing screenshot %s: %s", target, exc)
                    return False

            ss_coros = [_download_ss(i, u) for i, u in enumerate(ss_urls)]
            await asyncio.gather(*coros, *ss_coros, return_exceptions=True)

            if any(ss_dir.iterdir()):
                result["downloaded_screenshot_dir"] = ss_dir.relative_to(DATA_DIR).as_posix()
        else:
            await asyncio.gather(*coros, return_exceptions=True)

    return result
