"""外部图片本地缓存（Phase 3 图片处理策略落地）

"收藏入库"时把外部封面图缓存一份到本地 thumbnails 目录，避免大规模热链
导致的失效/带宽问题。默认展示原始链接；仅用户执行收藏入库时才缓存。

ADR 0034 补：从根源修复扩展名 bug——之前 `_guess_ext` 对无扩展名的 URL
（如 Bangumi 封面 `/pic/cover/l/xx/yy`）兜底写成 `.img`，导致 /static 以
octet-stream 提供、任何"fetch + blob.type 校验"的消费方（安利卡取色内联、
封面取色 data URL 回退）读不到。现改为**下载后按 Content-Type / 魔数识别
正确扩展名**再落盘；同时清理旧的错误 `.img` 残留，并支持出站代理。
"""
import hashlib
import os
from typing import Optional, Tuple

import httpx

from app.config import settings

# 已知图片 MIME → 扩展名
_MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/pjpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}

MAX_CACHE_BYTES = 5 * 1024 * 1024  # 防异常大图撑爆磁盘


class CoverDownloadError(Exception):
    """封面下载失败，message 为可直接展示的原因（网络不可达 / HTTP 错误 / 非图片）。"""


def _guess_ext(url: str) -> str:
    """从 URL 猜测扩展名（兜底；优先 Content-Type/魔数）。"""
    lower = url.lower().split("?")[0]
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        if lower.endswith(ext):
            return ext
    return ".img"


def _detect_image_ext(resp: httpx.Response) -> str:
    """按 Content-Type / 魔数识别图片扩展名（ADR 0034 补：根治 .img 问题）。

    优先响应头 Content-Type；缺失/异常时按文件头魔数嗅探；最后回退 URL 猜测。
    """
    ct = (resp.headers.get("content-type") or "").lower()
    for mime, ext in _MIME_TO_EXT.items():
        if ct.startswith(mime):
            return ext
    head = resp.content[:16]
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head[:2] == b"BM":
        return ".bmp"
    return _guess_ext(str(resp.url))


def _download(url: str, proxy: Optional[str], timeout: float = 15.0) -> httpx.Response:
    """下载图片字节；失败抛 CoverDownloadError（带具体原因）。"""
    try:
        resp = httpx.get(url, timeout=httpx.Timeout(timeout, connect=min(timeout, 6.0)),
                         follow_redirects=True, proxy=proxy)
    except httpx.ConnectTimeout:
        raise CoverDownloadError("连接超时（网络不可达）")
    except httpx.ConnectError:
        raise CoverDownloadError("连接失败（网络不可达）")
    except httpx.HTTPError as e:
        raise CoverDownloadError(f"HTTP 错误：{e}")
    if resp.status_code == 404:
        raise CoverDownloadError("图片不存在（404）")
    if resp.status_code >= 400:
        raise CoverDownloadError(f"HTTP {resp.status_code}")
    if len(resp.content) > MAX_CACHE_BYTES:
        raise CoverDownloadError("图片过大（>5MB）")
    return resp


def _find_cached(base: str) -> Optional[str]:
    """在 thumbnails 目录找同 md5 的**正确扩展名**缓存（跳过旧的 .img 残留）。"""
    try:
        for f in os.listdir(settings.thumbnails_dir):
            if f.startswith(base + "."):
                ext = os.path.splitext(f)[1].lower()
                if ext != ".img":
                    p = os.path.join(settings.thumbnails_dir, f)
                    if os.path.getsize(p) > 0:
                        return p
    except OSError:
        pass
    return None


def _cleanup_stale(base: str, keep: str) -> None:
    """清理同一 URL 的旧缓存文件（如错误扩展名的 .img 残留），保留新写入的文件。"""
    try:
        for f in os.listdir(settings.thumbnails_dir):
            if f.startswith(base + ".") and f != keep:
                try:
                    os.remove(os.path.join(settings.thumbnails_dir, f))
                except OSError:
                    pass
    except OSError:
        pass


def download_and_cache_cover(url: Optional[str], proxy: Optional[str] = None,
                             timeout: float = 15.0) -> Tuple[Optional[str], str]:
    """下载封面并写入本地缓存。返回 (本地路径, 说明)；失败时 (None, 具体原因)。"""
    if not url:
        return None, "无 URL"
    os.makedirs(settings.thumbnails_dir, exist_ok=True)
    base = hashlib.md5(url.encode("utf-8")).hexdigest()

    cached = _find_cached(base)
    if cached:
        return cached, "已有正确缓存"

    try:
        resp = _download(url, proxy, timeout=timeout)
        ext = _detect_image_ext(resp)
        if ext == ".img":
            # 下载成功但既无 MIME 也无魔数：非图片内容，视为失效
            return None, "非图片内容（无法识别格式）"
        path = os.path.join(settings.thumbnails_dir, base + ext)
        _cleanup_stale(base, os.path.basename(path))
        with open(path, "wb") as f:
            f.write(resp.content)
        return path, f"ok（{ext}）"
    except CoverDownloadError as e:
        return None, str(e)
    except OSError as e:
        return None, f"写入失败：{e}"


def cache_external_image(url: Optional[str], proxy: Optional[str] = None) -> Optional[str]:
    """把外部图片 URL 下载并缓存到本地，返回本地路径；失败返回 None
    （不阻塞收藏入库，仅当可下载时缓存）。"""
    path, _ = download_and_cache_cover(url, proxy)
    return path
