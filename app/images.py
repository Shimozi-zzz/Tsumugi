"""外部图片本地缓存（Phase 3 图片处理策略落地）

"收藏入库"时把外部封面图缓存一份到本地 thumbnails 目录，避免大规模热链
导致的失效/带宽问题。默认展示原始链接；仅用户执行收藏入库时才缓存。
"""
import hashlib
import os
from typing import Optional

import httpx

from app.config import settings


def cache_external_image(url: Optional[str]) -> Optional[str]:
    """把外部图片 URL 下载并缓存到本地，返回本地路径；失败返回 None
    （不阻塞收藏入库，仅当可下载时缓存）。"""
    if not url:
        return None
    os.makedirs(settings.thumbnails_dir, exist_ok=True)
    ext = _guess_ext(url)
    name = hashlib.md5(url.encode("utf-8")).hexdigest() + ext
    local_path = os.path.join(settings.thumbnails_dir, name)
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return local_path  # 已有缓存
    try:
        resp = httpx.get(url, timeout=10.0, follow_redirects=True)
        resp.raise_for_status()
        # 限制缓存大小（如 5MB），防止异常大图撑爆磁盘
        if len(resp.content) > 5 * 1024 * 1024:
            return None
        with open(local_path, "wb") as f:
            f.write(resp.content)
        return local_path
    except httpx.HTTPError:
        return None
    except OSError:
        return None


def _guess_ext(url: str) -> str:
    """从 URL 猜测扩展名，兜底 .img。"""
    lower = url.lower().split("?")[0]
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        if lower.endswith(ext):
            return ext
    return ".img"
