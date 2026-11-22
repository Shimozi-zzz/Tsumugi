import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.core.config import BACKUPS_DIR, DATA_DIR

_SAFE_NOTE_RE = re.compile(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+")


def _game_backup_dir(game_id: int) -> Path:
    d = BACKUPS_DIR / str(game_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_save_dir(save_dir: str) -> Path:
    target = Path(save_dir.strip())
    if not target.is_absolute():
        target = DATA_DIR / target
    return target


def create_save_backup(game_id: int, save_dir: str, note: str = "") -> dict[str, Any]:
    """将游戏存档目录打包为时间戳 ZIP 快照并存入 data/backups/{game_id}/"""
    if not save_dir or not save_dir.strip():
        raise ValueError("该游戏尚未绑定存档目录（save_dir）")

    src_dir = _resolve_save_dir(save_dir)
    if not src_dir.exists() or not src_dir.is_dir():
        raise FileNotFoundError(f"存档目录不存在: {src_dir}")

    backup_dir = _game_backup_dir(game_id)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_note = _SAFE_NOTE_RE.sub("_", note.strip())[:24].strip("_")
    filename = f"save_{ts}_{clean_note}.zip" if clean_note else f"save_{ts}.zip"
    zip_path = backup_dir / filename

    file_count = 0
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file_path in sorted(src_dir.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(src_dir).as_posix()
                zf.write(file_path, arcname=arcname)
                file_count += 1

    stat = zip_path.stat()
    return {
        "game_id": game_id,
        "filename": filename,
        "path": zip_path.relative_to(DATA_DIR).as_posix(),
        "size_bytes": stat.st_size,
        "file_count": file_count,
        "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
    }


def list_save_backups(game_id: int) -> list[dict[str, Any]]:
    """列出某游戏的所有存档压缩快照（按时间倒序）"""
    backup_dir = BACKUPS_DIR / str(game_id)
    if not backup_dir.exists():
        return []

    zips = [p for p in backup_dir.iterdir() if p.is_file() and p.suffix.lower() == ".zip"]
    zips.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    items: list[dict[str, Any]] = []
    for z in zips:
        stat = z.stat()
        items.append(
            {
                "game_id": game_id,
                "filename": z.name,
                "path": z.relative_to(DATA_DIR).as_posix(),
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )
    return items


def delete_save_backup(game_id: int, filename: str) -> bool:
    """安全删除指定快照文件（防路径穿越）"""
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name.endswith(".zip"):
        raise ValueError("非法的备份文件名")

    target = BACKUPS_DIR / str(game_id) / safe_name
    if not target.exists() or not target.is_file():
        return False
    target.unlink()
    return True


def restore_save_backup(game_id: int, save_dir: str, filename: str) -> dict[str, Any]:
    """将指定快照安全解压恢复至存档目录（恢复前自动先做一次安全快照）"""
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name.endswith(".zip"):
        raise ValueError("非法的备份文件名")

    zip_path = BACKUPS_DIR / str(game_id) / safe_name
    if not zip_path.exists():
        raise FileNotFoundError(f"找不到指定的备份文件: {safe_name}")

    dest_dir = _resolve_save_dir(save_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 恢复前先自动备份当前存档，避免误覆盖
    safety_backup = None
    if any(dest_dir.iterdir()):
        safety_backup = create_save_backup(game_id, save_dir, note="pre_restore")

    dest_resolved = dest_dir.resolve()
    restored_files = 0
    with zipfile.ZipFile(zip_path, mode="r") as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            target_path = (dest_resolved / member.filename).resolve()
            # 严格防御 Zip Slip 路径穿越
            if not str(target_path).startswith(str(dest_resolved)):
                raise ValueError(f"检测到非法压缩条目路径: {member.filename}")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member, "r") as src, target_path.open("wb") as dst:
                dst.write(src.read())
            restored_files += 1

    return {
        "restored": True,
        "filename": safe_name,
        "restored_files": restored_files,
        "safety_backup": safety_backup["filename"] if safety_backup else None,
    }
