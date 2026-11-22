import hashlib
import io
from pathlib import Path
from PIL import Image
from pypinyin import Style, pinyin
from backend.core.config import ASSETS_DIR, DATA_DIR, THUMBS_CACHE_DIR

WEBP_IMAGE_ASSET_TYPES = {"cover", "logo", "hero", "spine", "custom_spine"}


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
