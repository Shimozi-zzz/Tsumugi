"""
本地图片 WebP 缩略图服务（DATA_DIR/thumbs/）：
- 使用 Pillow + ImageOps.exif_transpose 纠正方向，LANCZOS 等比缩放（不放大原图），输出 WebP (quality=82, method=4)
- 完整保留 RGBA / LA / 调色板透明通道
- 缓存文件名由「原图相对路径 + mtime_ns + 文件大小 + 尺寸档位」短哈希组成，原图更新时自动失效
- 严格校验源图位于允许的本地图片目录内（防目录穿越）
- 源图损坏或非支持格式时安全降级返回原文件
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import threading
from typing import Iterable, Literal
from urllib.parse import quote, unquote

from PIL import Image, ImageOps

from backend.core.config import DATA_DIR, THUMBS_CACHE_DIR, THUMBS_DIR

logger = logging.getLogger("tsumugi.services.thumbnail_service")

ThumbSizePreset = Literal["sm", "md"]

THUMB_SIZE_PRESETS: dict[str, int] = {
    "sm": 360,
    "md": 720,
}

THUMB_WEBP_QUALITY = 82
THUMB_WEBP_METHOD = 4

ALLOWED_DATA_IMAGE_SUBDIRS: tuple[str, ...] = ("assets", "wallpapers")
SUPPORTED_IMAGE_EXTS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".tif", ".avif"}
)


def _path_hash(rel_key: str) -> str:
    return hashlib.blake2b(rel_key.encode("utf-8"), digest_size=6).hexdigest()


def build_thumb_cache_filename(
    rel_key: str,
    mtime_ns: int,
    file_size: int,
    size_tag: str,
) -> str:
    """构造缩略图缓存文件名：{path_hash}_{ver_hash}_{size_tag}.webp"""
    p_hash = _path_hash(rel_key)
    v_hash = hashlib.blake2b(
        f"{rel_key}|{mtime_ns}|{file_size}|{size_tag}".encode("utf-8"),
        digest_size=8,
    ).hexdigest()
    return f"{p_hash}_{v_hash}_{size_tag}.webp"


def normalize_local_image_ref(raw_path: str) -> str:
    """规范化前端传入的相对路径或 /static/data/... 资产 URL，去除查询参数并拦截危险协议"""
    if not raw_path or not isinstance(raw_path, str):
        raise PermissionError("图片路径不能为空")
    cleaned = unquote(raw_path).strip()
    if not cleaned or "\x00" in cleaned:
        raise PermissionError("图片路径包含非法字符")

    # 去除 ?v=... 与 #... 片段
    cleaned = cleaned.split("#", 1)[0].split("?", 1)[0].strip()
    low = cleaned.lower()
    if low.startswith(("http://", "https://", "file://", "data:", "javascript:")):
        raise PermissionError("不支持为远程链接生成本地缩略图")

    cleaned = cleaned.replace("\\", "/")
    for prefix in ("/static/data/", "static/data/"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break

    return cleaned.strip()


def resolve_allowed_image_path(
    raw_path: str,
    *,
    data_dir: Path | None = None,
    extra_allowed_roots: Iterable[Path] | None = None,
) -> tuple[Path, str]:
    """
    严格校验并解析本地图片源路径：
    - 默认仅允许访问 DATA_DIR/assets 与 DATA_DIR/wallpapers 下的文件，杜绝目录穿越（../、符号链接逃逸、访问 backups/db/settings）
    - 若调用方显式传入 extra_allowed_roots（如数据库中已登记的本地游戏截图目录），也校验其边界
    返回 (resolved_path, stable_rel_key)
    """
    normalized = normalize_local_image_ref(raw_path)
    base_data = (data_dir if data_dir is not None else DATA_DIR).resolve()

    allowed_roots: list[Path] = [
        (base_data / sub).resolve() for sub in ALLOWED_DATA_IMAGE_SUBDIRS
    ]
    if extra_allowed_roots:
        for root in extra_allowed_roots:
            try:
                r = Path(root).expanduser().resolve()
                if r.is_dir() and r not in allowed_roots:
                    allowed_roots.append(r)
            except OSError:
                continue

    # 禁止路径中显式包含 ".." 段
    path_parts = [part for part in normalized.split("/") if part]
    if ".." in path_parts:
        raise PermissionError("检测到非法目录穿越路径")

    candidate = Path(normalized)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        rel_clean = normalized.lstrip("/")
        if not rel_clean:
            raise PermissionError("图片路径为空")
        resolved = (base_data / rel_clean).resolve()

    matched_root: Path | None = None
    for root in allowed_roots:
        if resolved.is_relative_to(root):
            matched_root = root
            break

    if matched_root is None:
        raise PermissionError("禁止访问允许的图片目录之外的文件")

    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"目标图片不存在: {raw_path}")

    try:
        rel_key = resolved.relative_to(base_data).as_posix()
    except ValueError:
        rel_key = f"ext/{resolved.as_posix()}"

    return resolved, rel_key


def _resolve_target_spec(
    *,
    size: str | None = None,
    width: int | None = None,
) -> tuple[int, str]:
    if size is not None and str(size).strip():
        norm_size = str(size).strip().lower()
        if norm_size not in THUMB_SIZE_PRESETS:
            raise ValueError(f"不支持的缩略图尺寸档位: {size!r}（仅支持 sm / md）")
        return THUMB_SIZE_PRESETS[norm_size], norm_size

    if width is not None:
        clamped = max(80, min(1200, int(width)))
        for preset_name, preset_w in THUMB_SIZE_PRESETS.items():
            if clamped == preset_w:
                return preset_w, preset_name
        return clamped, f"w{clamped}"

    return THUMB_SIZE_PRESETS["sm"], "sm"


def get_or_create_webp_thumbnail(
    raw_path: str,
    *,
    size: str | None = None,
    width: int | None = None,
    data_dir: Path | None = None,
    thumbs_dir: Path | None = None,
    extra_allowed_roots: Iterable[Path] | None = None,
) -> tuple[Path, bool]:
    """
    获取或按需生成 WebP 缩略图：
    - 返回 (file_path, is_generated_webp_thumb)
    - 命中 DATA_DIR/thumbs/ 缓存直接返回 (thumb_path, True)
    - 源文件损坏或非支持格式时安全降级返回 (source_path, False)
    """
    target_width, size_tag = _resolve_target_spec(size=size, width=width)
    source_path, rel_key = resolve_allowed_image_path(
        raw_path,
        data_dir=data_dir,
        extra_allowed_roots=extra_allowed_roots,
    )

    out_dir = (thumbs_dir if thumbs_dir is not None else THUMBS_DIR).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    stat = source_path.stat()
    cache_name = build_thumb_cache_filename(
        rel_key=rel_key,
        mtime_ns=stat.st_mtime_ns,
        file_size=stat.st_size,
        size_tag=size_tag,
    )
    thumb_path = out_dir / cache_name

    if thumb_path.is_file():
        try:
            if thumb_path.stat().st_size > 0:
                return thumb_path, True
        except OSError:
            pass

    if source_path.suffix.lower() not in SUPPORTED_IMAGE_EXTS:
        return source_path, False

    tmp_path = out_dir / f"{thumb_path.stem}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with Image.open(source_path) as raw_img:
            img = ImageOps.exif_transpose(raw_img)
            has_alpha = img.mode in ("RGBA", "LA", "PA") or (
                img.mode == "P" and "transparency" in img.info
            )
            prepared = img.convert("RGBA" if has_alpha else "RGB")

            if prepared.width > target_width:
                ratio = target_width / max(prepared.width, 1)
                new_height = max(1, int(round(prepared.height * ratio)))
                prepared = prepared.resize((target_width, new_height), Image.Resampling.LANCZOS)

            prepared.save(
                tmp_path,
                format="WEBP",
                quality=THUMB_WEBP_QUALITY,
                method=THUMB_WEBP_METHOD,
            )

        if not tmp_path.is_file() or tmp_path.stat().st_size <= 0:
            tmp_path.unlink(missing_ok=True)
            return source_path, False

        os.replace(tmp_path, thumb_path)

        # 顺手清理同一原图同一尺寸档位的旧版本缓存，防止原图频繁替换后残留旧文件
        p_hash = _path_hash(rel_key)
        for stale in out_dir.glob(f"{p_hash}_*_{size_tag}.webp"):
            if stale.name != thumb_path.name and stale.is_file():
                try:
                    stale.unlink()
                except OSError:
                    pass

        return thumb_path, True
    except Exception as exc:
        logger.debug("Thumbnail generation degraded to raw source for %s: %s", source_path, exc)
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return source_path, False


def invalidate_thumbnails_for_path(
    raw_path: str | None,
    *,
    data_dir: Path | None = None,
    thumbs_dir: Path | None = None,
) -> int:
    """删除指定原图在 DATA_DIR/thumbs/ 下全部尺寸档位的缩略图缓存"""
    if not raw_path or not str(raw_path).strip():
        return 0
    try:
        normalized = normalize_local_image_ref(str(raw_path))
    except PermissionError:
        return 0

    out_dir = (thumbs_dir if thumbs_dir is not None else THUMBS_DIR).resolve()
    if not out_dir.exists() or not out_dir.is_dir():
        return 0

    base_data = (data_dir if data_dir is not None else DATA_DIR).resolve()
    rel_key = normalized.lstrip("/")
    cand = Path(normalized)
    if cand.is_absolute():
        try:
            rel_key = cand.resolve().relative_to(base_data).as_posix()
        except ValueError:
            rel_key = f"ext/{cand.resolve().as_posix()}"

    p_hash = _path_hash(rel_key)
    removed = 0
    for fp in out_dir.glob(f"{p_hash}_*.webp"):
        if fp.is_file():
            try:
                fp.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def invalidate_thumbnails_for_game(
    game_id: int,
    *,
    data_dir: Path | None = None,
    thumbs_dir: Path | None = None,
) -> int:
    """游戏删除前清理该游戏资产目录下所有图片对应的缩略图缓存"""
    base_data = (data_dir if data_dir is not None else DATA_DIR).resolve()
    game_dir = base_data / "assets" / str(game_id)
    if not game_dir.exists() or not game_dir.is_dir():
        return 0

    removed = 0
    for root_str, _dirs, files in os.walk(game_dir):
        root_path = Path(root_str)
        for fname in files:
            fp = root_path / fname
            if fp.suffix.lower() not in SUPPORTED_IMAGE_EXTS:
                continue
            try:
                rel = fp.resolve().relative_to(base_data).as_posix()
            except ValueError:
                continue
            removed += invalidate_thumbnails_for_path(
                rel,
                data_dir=base_data,
                thumbs_dir=thumbs_dir,
            )
    return removed


def clear_thumbnail_cache(
    *,
    thumbs_dir: Path | None = None,
    legacy_cache_dir: Path | None = None,
) -> dict[str, int]:
    """一键清空 DATA_DIR/thumbs/（及旧版 data/cache/thumbs/）全部缩略图缓存"""
    dirs_to_clear: list[Path] = [
        (thumbs_dir if thumbs_dir is not None else THUMBS_DIR).resolve()
    ]
    if legacy_cache_dir is not None:
        dirs_to_clear.append(legacy_cache_dir.resolve())
    elif thumbs_dir is None:
        dirs_to_clear.append(THUMBS_CACHE_DIR.resolve())

    deleted_files = 0
    freed_bytes = 0

    for target_dir in dirs_to_clear:
        if not target_dir.exists() or not target_dir.is_dir():
            continue
        for root_str, _dirs, files in os.walk(target_dir):
            root_path = Path(root_str)
            for fname in files:
                fp = root_path / fname
                if fp.is_symlink() or not fp.is_file():
                    continue
                try:
                    sz = fp.stat().st_size
                    fp.unlink()
                    deleted_files += 1
                    freed_bytes += sz
                except OSError:
                    pass

    return {
        "deleted_files": deleted_files,
        "freed_bytes": freed_bytes,
    }


def prewarm_cover_thumbnails(
    cover_paths: Iterable[str],
    *,
    size: ThumbSizePreset = "sm",
    data_dir: Path | None = None,
    thumbs_dir: Path | None = None,
) -> dict[str, int]:
    """后台静默为现有游戏库中尚未生成缩略图的本地封面预热生成 WebP 缩略图"""
    generated = 0
    skipped = 0
    failed = 0

    for raw in cover_paths:
        cleaned = (raw or "").strip()
        if not cleaned or cleaned.lower().startswith(("http://", "https://")):
            skipped += 1
            continue
        try:
            _, is_thumb = get_or_create_webp_thumbnail(
                cleaned,
                size=size,
                data_dir=data_dir,
                thumbs_dir=thumbs_dir,
            )
            if is_thumb:
                generated += 1
            else:
                skipped += 1
        except (FileNotFoundError, PermissionError):
            skipped += 1
        except Exception:
            failed += 1

    return {"generated": generated, "skipped": skipped, "failed": failed}


def build_thumb_api_url(
    raw_path: str | None,
    size: ThumbSizePreset = "sm",
) -> str:
    """将本地图片相对路径转换为轻量缩略图接口 URL（远程链接或空值返回空字符串）"""
    if not raw_path or not isinstance(raw_path, str):
        return ""
    cleaned = raw_path.strip()
    if not cleaned:
        return ""
    low = cleaned.lower()
    if low.startswith(("http://", "https://", "data:")):
        return ""
    try:
        norm = normalize_local_image_ref(cleaned).lstrip("/")
    except PermissionError:
        return ""
    if not norm:
        return ""
    first_seg = norm.split("/", 1)[0]
    if first_seg not in ALLOWED_DATA_IMAGE_SUBDIRS:
        return ""
    return f"/api/media/thumb?path={quote(norm, safe='/')}&size={size}"
