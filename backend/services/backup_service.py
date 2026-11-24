"""
备份与恢复服务：
1. 单游戏存档备份与恢复（data/backups/{game_id}/）
2. SQLite 在线热备自动快照（data/backups/auto/，严格使用 sqlite3.Connection.backup() + PRAGMA quick_check，保留最近 5 份）
3. 整库一键导出（.zip，包含 manifest.json + 一致性 tsumugi.db + settings.json + 图片资产 + 可选影音，严格排除 backups/thumbs/log/tmp/wal/shm）
4. 整库安全恢复与自动快照回滚（防 Zip Slip + PRAGMA integrity_check + pre_restore 保护快照 + engine.dispose 释放文件锁 + 清理 -wal/-shm + 清空 thumbs）
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import threading
from typing import Any, Awaitable, Callable, Literal
import zipfile

from backend.core.config import (
    APP_VERSION,
    AUTO_BACKUPS_DIR,
    BACKUPS_DIR,
    DATA_DIR,
    DB_PATH,
    THUMBS_CACHE_DIR,
    THUMBS_DIR,
)
from backend.services.thumbnail_service import clear_thumbnail_cache

logger = logging.getLogger("tsumugi.services.backup_service")

_SAFE_NOTE_RE = re.compile(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+")

BACKUP_FORMAT_VERSION = 1
AUTO_SNAPSHOT_MIN_INTERVAL_SECONDS = 600  # 10 分钟
AUTO_SNAPSHOT_MAX_KEEP = 5
SAFETY_SNAPSHOT_MAX_KEEP = 10

SnapshotTag = Literal["auto", "pre_restore", "pre_import"]

SNAPSHOT_TAG_LABELS: dict[str, str] = {
    "auto": "自动快照",
    "pre_restore": "恢复前保护",
    "pre_import": "导入前保护",
}

EXPORT_EXCLUDED_TOP_DIRS: frozenset[str] = frozenset(
    {"backups", "thumbs", "cache", "webview_cache"}
)
EXPORT_EXCLUDED_SUFFIXES: frozenset[str] = frozenset(
    {".log", ".tmp", ".part", ".ytdl"}
)
VIDEO_MEDIA_EXTS: frozenset[str] = frozenset(
    {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi"}
)
AUDIO_MEDIA_EXTS: frozenset[str] = frozenset(
    {".m4a", ".mp3", ".flac", ".ogg", ".wav", ".opus"}
)
PRECOMPRESSED_EXTS: frozenset[str] = frozenset(
    {
        ".webp",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".avif",
        ".mp4",
        ".webm",
        ".mkv",
        ".mov",
        ".m4v",
        ".m4a",
        ".mp3",
        ".ogg",
        ".opus",
    }
)


# ──────────────────── 1. 单游戏存档备份与恢复（既有功能保持兼容） ────────────────────


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
            if not target_path.is_relative_to(dest_resolved):
                raise ValueError(f"检测到非法压缩条目路径: {member.filename}")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member, "r") as src, target_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            restored_files += 1

    return {
        "restored": True,
        "filename": safe_name,
        "restored_files": restored_files,
        "safety_backup": safety_backup["filename"] if safety_backup else None,
    }


# ──────────────────── 2. SQLite 在线热备与启动自动快照 ────────────────────


def verify_sqlite_integrity(
    db_path: Path,
    *,
    full: bool = False,
    require_games_table: bool = False,
) -> None:
    """
    校验 SQLite 数据库文件完整性：
    - full=False 使用 PRAGMA quick_check（自动快照导出后快速校验）
    - full=True 使用 PRAGMA integrity_check（整库恢复/回滚前严格校验）
    """
    if not db_path.is_file() or db_path.stat().st_size < 16:
        raise ValueError("数据库文件不存在或已损坏")

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_path), timeout=15.0)
        pragma_sql = "PRAGMA integrity_check" if full else "PRAGMA quick_check"
        rows = conn.execute(pragma_sql).fetchall()
        if not rows or any(str(r[0]).lower() != "ok" for r in rows):
            detail = "; ".join(str(r[0]) for r in rows[:3]) or "unknown"
            raise ValueError(f"SQLite 完整性校验失败: {detail}")

        if require_games_table:
            table_row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='games'"
            ).fetchone()
            if table_row is None:
                raise ValueError("备份数据库缺少核心 games 数据表，无法恢复")
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"无效或已损坏的 SQLite 数据库文件: {exc}") from exc
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def sqlite_hot_backup(src_db: Path, dst_db: Path) -> None:
    """
    使用 Python 标准库 sqlite3.Connection.backup() 执行安全在线热备（兼容 WAL 模式与并发读取），
    完成后以 PRAGMA quick_check 校验完整性并原子落盘。
    """
    if not src_db.is_file():
        raise FileNotFoundError(f"源数据库文件不存在: {src_db}")

    dst_db.parent.mkdir(parents=True, exist_ok=True)
    tmp_dst = dst_db.with_name(f"{dst_db.name}.{os.getpid()}.{threading.get_ident()}.tmp")

    src_conn: sqlite3.Connection | None = None
    dst_conn: sqlite3.Connection | None = None
    try:
        src_conn = sqlite3.connect(str(src_db), timeout=30.0)
        dst_conn = sqlite3.connect(str(tmp_dst), timeout=30.0)
        src_conn.backup(dst_conn)
        dst_conn.commit()
    except Exception:
        if dst_conn is not None:
            try:
                dst_conn.close()
                dst_conn = None
            except Exception:
                pass
        tmp_dst.unlink(missing_ok=True)
        raise
    finally:
        if dst_conn is not None:
            try:
                dst_conn.close()
            except Exception:
                pass
        if src_conn is not None:
            try:
                src_conn.close()
            except Exception:
                pass

    try:
        verify_sqlite_integrity(tmp_dst, full=False)
        os.replace(tmp_dst, dst_db)
    except Exception:
        tmp_dst.unlink(missing_ok=True)
        raise


def _detect_snapshot_tag(filename: str) -> str:
    low = filename.lower()
    if low.startswith("tsumugi_pre_restore_"):
        return "pre_restore"
    if low.startswith("tsumugi_pre_import_"):
        return "pre_import"
    return "auto"


def _format_snapshot_entry(fp: Path) -> dict[str, Any]:
    stat = fp.stat()
    tag = _detect_snapshot_tag(fp.name)
    return {
        "filename": fp.name,
        "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "size_bytes": stat.st_size,
        "tag": tag,
        "tag_label": SNAPSHOT_TAG_LABELS.get(tag, "自动快照"),
    }


def list_auto_snapshots(*, auto_dir: Path | None = None) -> list[dict[str, Any]]:
    """按时间倒序列出 DATA_DIR/backups/auto/ 下的全部数据库快照"""
    target_dir = (auto_dir if auto_dir is not None else AUTO_BACKUPS_DIR).resolve()
    if not target_dir.exists() or not target_dir.is_dir():
        return []

    files = [
        p for p in target_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".db" and not p.name.endswith(".tmp")
    ]
    files.sort(key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    return [_format_snapshot_entry(p) for p in files]


def create_auto_snapshot(
    *,
    tag: SnapshotTag = "auto",
    force: bool = False,
    min_interval_seconds: int = AUTO_SNAPSHOT_MIN_INTERVAL_SECONDS,
    max_keep: int = AUTO_SNAPSHOT_MAX_KEEP,
    db_path: Path | None = None,
    auto_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """
    创建一份 SQLite 在线热备快照（存放于 DATA_DIR/backups/auto/）：
    - tag='auto' 且 force=False 时：若距离最近一份自动快照不足 min_interval_seconds（默认 10 分钟），静默跳过返回 None；
    - 导出后执行 PRAGMA quick_check 完整性校验；
    - 自动轮转：常规 auto 快照仅保留最近 max_keep 份（默认 5 份），更早的自动清理。
    """
    src_db = (db_path if db_path is not None else DB_PATH).resolve()
    if not src_db.is_file() or src_db.stat().st_size == 0:
        return None

    target_dir = (auto_dir if auto_dir is not None else AUTO_BACKUPS_DIR).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    current_dt = now if now is not None else datetime.now()
    current_ts = current_dt.timestamp()

    if tag == "auto" and not force and min_interval_seconds > 0:
        existing_auto = [
            p for p in target_dir.glob("tsumugi_auto_*.db")
            if p.is_file()
        ]
        if existing_auto:
            latest = max(existing_auto, key=lambda p: (p.stat().st_mtime_ns, p.name))
            elapsed = current_ts - latest.stat().st_mtime
            if elapsed < min_interval_seconds:
                return None

    ts_label = current_dt.strftime("%Y%m%d_%H%M%S")
    prefix = f"tsumugi_{tag}"
    candidate = target_dir / f"{prefix}_{ts_label}.db"
    seq = 1
    while candidate.exists():
        candidate = target_dir / f"{prefix}_{ts_label}_{seq:02d}.db"
        seq += 1

    sqlite_hot_backup(src_db, candidate)

    # 若测试注入了自定义 now 时间戳，同步落盘 mtime 以便轮转排序与间隔判断准确
    if now is not None:
        os.utime(candidate, (current_ts, current_ts))

    # 轮转清理：auto 快照严格保留最近 max_keep 份；保护快照保留最近 SAFETY_SNAPSHOT_MAX_KEEP 份
    keep_limit = max(1, int(max_keep)) if tag == "auto" else SAFETY_SNAPSHOT_MAX_KEEP
    same_tag_files = [p for p in target_dir.glob(f"{prefix}_*.db") if p.is_file()]
    same_tag_files.sort(key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    for stale in same_tag_files[keep_limit:]:
        try:
            stale.unlink()
        except OSError:
            pass

    return _format_snapshot_entry(candidate)


# ──────────────────── 3. 整库一键导出 (.zip) 与安全恢复 / 快照回滚 ────────────────────


def default_backup_zip_filename(now: datetime | None = None) -> str:
    dt = now if now is not None else datetime.now()
    return f"Tsumugi-Backup-{dt.strftime('%Y%m%d-%H%M%S')}.zip"


def _is_excluded_export_file(rel_posix: str, filename: str, *, include_videos: bool) -> bool:
    parts = [p for p in rel_posix.split("/") if p]
    if not parts:
        return True
    if parts[0].lower() in EXPORT_EXCLUDED_TOP_DIRS:
        return True

    low_name = filename.lower()
    suffix = Path(filename).suffix.lower()
    if suffix in EXPORT_EXCLUDED_SUFFIXES:
        return True
    if ".downloading." in low_name or low_name.endswith(".downloading"):
        return True
    if low_name.endswith(("-wal", "-shm", "-journal")):
        return True
    if low_name.startswith("tsumugi.db"):
        return True

    if not include_videos and suffix in (VIDEO_MEDIA_EXTS | AUDIO_MEDIA_EXTS):
        return True

    return False


def _count_games_in_sqlite(db_file: Path) -> int:
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_file), timeout=10.0)
        row = conn.execute("SELECT COUNT(*) FROM games").fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def export_library_backup_zip(
    output_zip: Path,
    *,
    include_videos: bool = False,
    data_dir: Path | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """
    将整个 Tsumugi 资料库打包为可移植 .zip 备份：
    - 使用 sqlite3.backup() 在临时目录生成一致性数据库副本 tsumugi.db
    - 包含 manifest.json、tsumugi.db、settings.json（若存在）及 data/assets、data/wallpapers 下的本地图片资产
    - include_videos=True 时一并打包本地 PV/OP 影音缓存
    - 严格排除 backups/、thumbs/、cache/、*.log、*.tmp、*-wal、*-shm
    """
    base_data = (data_dir if data_dir is not None else DATA_DIR).resolve()
    src_db = (db_path if db_path is not None else (base_data / "tsumugi.db" if data_dir is not None else DB_PATH)).resolve()
    if not src_db.is_file():
        raise FileNotFoundError(f"找不到数据库文件: {src_db}")

    output_zip = Path(output_zip).expanduser()
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    tmp_zip = output_zip.with_name(
        f"{output_zip.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )

    with tempfile.TemporaryDirectory(prefix="tsumugi_export_") as tmp_str:
        tmp_dir = Path(tmp_str)
        staged_db = tmp_dir / "tsumugi.db"
        sqlite_hot_backup(src_db, staged_db)
        game_count = _count_games_in_sqlite(staged_db)

        files_to_pack: list[tuple[Path, str]] = []

        settings_file = base_data / "settings.json"
        if settings_file.is_file():
            files_to_pack.append((settings_file, "settings.json"))

        for sub_name in ("assets", "wallpapers"):
            sub_dir = base_data / sub_name
            if not sub_dir.exists() or not sub_dir.is_dir():
                continue
            for root_str, dirs, files in os.walk(sub_dir):
                # 原地过滤不应进入的子目录
                dirs[:] = sorted(
                    d for d in dirs if d.lower() not in EXPORT_EXCLUDED_TOP_DIRS
                )
                root_path = Path(root_str)
                for fname in sorted(files):
                    fp = root_path / fname
                    if fp.is_symlink() or not fp.is_file():
                        continue
                    try:
                        rel_posix = fp.resolve().relative_to(base_data).as_posix()
                    except ValueError:
                        continue
                    if _is_excluded_export_file(rel_posix, fname, include_videos=include_videos):
                        continue
                    files_to_pack.append((fp, rel_posix))

        manifest: dict[str, Any] = {
            "app": "Tsumugi",
            "app_version": APP_VERSION,
            "backup_version": BACKUP_FORMAT_VERSION,
            "created_at": datetime.now().isoformat(),
            "game_count": game_count,
            "include_videos": bool(include_videos),
            "files_count": len(files_to_pack) + 2,  # + tsumugi.db + manifest.json
        }

        try:
            with zipfile.ZipFile(
                tmp_zip,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
                allowZip64=True,
            ) as zf:
                zf.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                    compress_type=zipfile.ZIP_DEFLATED,
                )
                zf.write(staged_db, arcname="tsumugi.db", compress_type=zipfile.ZIP_DEFLATED)

                for src_file, arcname in files_to_pack:
                    comp = (
                        zipfile.ZIP_STORED
                        if src_file.suffix.lower() in PRECOMPRESSED_EXTS
                        else zipfile.ZIP_DEFLATED
                    )
                    zf.write(src_file, arcname=arcname, compress_type=comp)

            os.replace(tmp_zip, output_zip)
        except Exception:
            tmp_zip.unlink(missing_ok=True)
            raise

    size_bytes = output_zip.stat().st_size
    return {
        "exported": True,
        "filename": output_zip.name,
        "path": str(output_zip),
        "size_bytes": size_bytes,
        "file_count": manifest["files_count"],
        "manifest": manifest,
    }


def _validate_zip_member_relpath(raw_name: str, member: zipfile.ZipInfo) -> str:
    """严格校验 Zip 成员路径，阻断 Zip Slip 目录穿越、绝对路径、盘符与符号链接攻击"""
    if not raw_name or "\x00" in raw_name:
        raise ValueError(f"检测到非法压缩条目路径: {raw_name!r}")

    # 检测 Unix 符号链接条目（S_IFLNK = 0o120000）
    unix_mode = (member.external_attr >> 16) & 0o170000
    if unix_mode == 0o120000:
        raise ValueError(f"出于安全限制，备份包不允许包含符号链接: {raw_name}")

    normalized = raw_name.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[a-zA-Z]:", normalized):
        raise ValueError(f"检测到绝对路径越权条目（Zip Slip）: {raw_name}")

    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError(f"检测到上级目录穿越条目（Zip Slip）: {raw_name}")

    return "/".join(parts)


def validate_and_extract_backup_zip(zip_path: Path, extract_dir: Path) -> dict[str, Any]:
    """
    安全校验并解压整库备份压缩包至独立临时目录：
    - 严防 Zip Slip 路径穿越与符号链接
    - 校验存在有效 tsumugi.db 并通过 PRAGMA integrity_check 及 games 表检查
    """
    if not zip_path.is_file():
        raise FileNotFoundError(f"找不到指定的备份压缩包: {zip_path}")

    extract_root = extract_dir.resolve()
    extract_root.mkdir(parents=True, exist_ok=True)
    extracted_count = 0

    try:
        with zipfile.ZipFile(zip_path, mode="r") as zf:
            for member in zf.infolist():
                safe_rel = _validate_zip_member_relpath(member.filename, member)
                if not safe_rel:
                    continue
                target_path = (extract_root / safe_rel).resolve()
                if not target_path.is_relative_to(extract_root):
                    raise ValueError(f"检测到越权解压路径（Zip Slip）: {member.filename}")
                if member.is_dir():
                    target_path.mkdir(parents=True, exist_ok=True)
                    continue

                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member, "r") as src, target_path.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted_count += 1
    except zipfile.BadZipFile as exc:
        raise ValueError("所选文件不是有效的 ZIP 备份压缩包") from exc

    extracted_db = extract_root / "tsumugi.db"
    if not extracted_db.is_file():
        raise ValueError("备份压缩包内缺少核心数据库文件 tsumugi.db")

    verify_sqlite_integrity(extracted_db, full=True, require_games_table=True)

    manifest: dict[str, Any] = {}
    manifest_file = extract_root / "manifest.json"
    if manifest_file.is_file():
        try:
            parsed = json.loads(manifest_file.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                manifest = parsed
        except Exception:
            manifest = {}

    settings_file = extract_root / "settings.json"
    if settings_file.is_file():
        try:
            parsed_cfg = json.loads(settings_file.read_text(encoding="utf-8"))
            if not isinstance(parsed_cfg, dict):
                settings_file = None  # type: ignore[assignment]
        except Exception:
            settings_file = None  # type: ignore[assignment]
    else:
        settings_file = None  # type: ignore[assignment]

    assets_dir = extract_root / "assets"
    wallpapers_dir = extract_root / "wallpapers"

    return {
        "db_file": extracted_db,
        "settings_file": settings_file,
        "assets_dir": assets_dir if assets_dir.is_dir() else None,
        "wallpapers_dir": wallpapers_dir if wallpapers_dir.is_dir() else None,
        "manifest": manifest,
        "extracted_files": extracted_count,
    }


def _remove_sqlite_sidecars(db_path: Path) -> list[str]:
    """清理目标 SQLite 数据库旁的残留 -wal / -shm / -journal 文件，避免旧 WAL 覆盖恢复后的新库"""
    removed: list[str] = []
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{db_path}{suffix}")
        if sidecar.exists() and sidecar.is_file():
            sidecar.unlink()
            removed.append(sidecar.name)
    return removed


def _atomic_copy_file(src: Path, dst: Path) -> None:
    """在目标目录同文件系统暂存后原子替换，规避跨设备 os.replace 失败"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    staged = dst.with_name(f"{dst.name}.restoring.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        shutil.copy2(src, staged)
        os.replace(staged, dst)
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def _sync_restored_directory(src_dir: Path, dst_dir: Path, *, preserve_videos: bool = False) -> int:
    """
    将备份解压出的资产目录同步至目标目录：
    - 若 preserve_videos=True（备份未含影音），跳过覆盖时保留既有本地影音；否则完整以备份内容为准
    """
    dst_dir.mkdir(parents=True, exist_ok=True)

    # 先清理目标中不再属于备份的旧文件（若 preserve_videos=True，保留原本地视频/音频）
    for root_str, dirs, files in os.walk(dst_dir, topdown=False):
        root_path = Path(root_str)
        for fname in files:
            fp = root_path / fname
            if fp.is_symlink():
                continue
            if preserve_videos and fp.suffix.lower() in (VIDEO_MEDIA_EXTS | AUDIO_MEDIA_EXTS):
                continue
            try:
                fp.unlink()
            except OSError:
                pass
        for dname in dirs:
            dp = root_path / dname
            try:
                if dp.is_dir() and not any(dp.iterdir()):
                    dp.rmdir()
            except OSError:
                pass

    copied = 0
    for root_str, _dirs, files in os.walk(src_dir):
        root_path = Path(root_str)
        for fname in files:
            src_file = root_path / fname
            if src_file.is_symlink() or not src_file.is_file():
                continue
            rel = src_file.relative_to(src_dir)
            target = dst_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, target)
            copied += 1
    return copied


async def restore_library_from_zip(
    zip_path: Path,
    *,
    dispose_engine: Callable[[], Awaitable[None]],
    reinit_db: Callable[[], Awaitable[Any]],
    data_dir: Path | None = None,
    db_path: Path | None = None,
    auto_dir: Path | None = None,
    thumbs_dir: Path | None = None,
) -> dict[str, Any]:
    """
    从整库 .zip 备份安全恢复：
    1. 在独立临时目录严格防 Zip Slip 解压，并执行 PRAGMA integrity_check 校验 tsumugi.db；
    2. 为当前运行中的库生成一份 pre_restore 保护快照；
    3. 调用 await engine.dispose() 彻底释放 SQLite 句柄（解决 Windows 文件锁）；
    4. 删除残留 -wal / -shm，原子替换 tsumugi.db、恢复 settings.json 与图片资产；
    5. 清空 DATA_DIR/thumbs/ 使缩略图按新库重新生成，重新执行 init_db() 平滑迁移。
    """
    base_data = (data_dir if data_dir is not None else DATA_DIR).resolve()
    target_db = (
        db_path
        if db_path is not None
        else (base_data / "tsumugi.db" if data_dir is not None else DB_PATH)
    ).resolve()
    target_auto = (
        auto_dir
        if auto_dir is not None
        else (base_data / "backups" / "auto" if data_dir is not None else AUTO_BACKUPS_DIR)
    ).resolve()
    target_thumbs = (
        thumbs_dir
        if thumbs_dir is not None
        else (base_data / "thumbs" if data_dir is not None else THUMBS_DIR)
    ).resolve()
    legacy_thumbs = (base_data / "cache" / "thumbs").resolve() if data_dir is not None else THUMBS_CACHE_DIR.resolve()

    with tempfile.TemporaryDirectory(prefix="tsumugi_restore_") as tmp_str:
        extracted = await asyncio.to_thread(
            validate_and_extract_backup_zip,
            zip_path,
            Path(tmp_str),
        )

        # 恢复前先为当前库留存一份 pre_restore 安全快照
        safety_snapshot = await asyncio.to_thread(
            create_auto_snapshot,
            tag="pre_restore",
            force=True,
            db_path=target_db,
            auto_dir=target_auto,
        )

        # 关键：彻底释放 SQLAlchemy 连接池句柄（避免 Windows 文件占用锁死）
        await dispose_engine()

        def _swap_files_sync() -> tuple[list[str], int, dict[str, int]]:
            removed_sidecars = _remove_sqlite_sidecars(target_db)
            _atomic_copy_file(extracted["db_file"], target_db)

            if extracted["settings_file"] is not None:
                _atomic_copy_file(extracted["settings_file"], base_data / "settings.json")

            include_videos_in_backup = bool((extracted["manifest"] or {}).get("include_videos", False))
            restored_assets = 0
            if extracted["assets_dir"] is not None:
                restored_assets += _sync_restored_directory(
                    extracted["assets_dir"],
                    base_data / "assets",
                    preserve_videos=not include_videos_in_backup,
                )
            if extracted["wallpapers_dir"] is not None:
                restored_assets += _sync_restored_directory(
                    extracted["wallpapers_dir"],
                    base_data / "wallpapers",
                    preserve_videos=False,
                )

            cleared_thumbs = clear_thumbnail_cache(
                thumbs_dir=target_thumbs,
                legacy_cache_dir=legacy_thumbs,
            )
            return removed_sidecars, restored_assets, cleared_thumbs

        removed_sidecars, restored_assets, cleared_thumbs = await asyncio.to_thread(_swap_files_sync)

    # 重建连接池并执行平滑建表/增量列迁移
    await reinit_db()

    return {
        "restored": True,
        "safety_snapshot": safety_snapshot["filename"] if safety_snapshot else None,
        "manifest": extracted["manifest"],
        "removed_sidecars": removed_sidecars,
        "restored_assets": restored_assets,
        "cleared_thumbs": cleared_thumbs["deleted_files"],
    }


async def restore_database_from_snapshot(
    filename: str,
    *,
    dispose_engine: Callable[[], Awaitable[None]],
    reinit_db: Callable[[], Awaitable[Any]],
    data_dir: Path | None = None,
    db_path: Path | None = None,
    auto_dir: Path | None = None,
    thumbs_dir: Path | None = None,
) -> dict[str, Any]:
    """
    从 DATA_DIR/backups/auto/ 回滚指定自动快照：
    - 防路径穿越 + PRAGMA integrity_check
    - 回滚前自动创建 pre_restore 保护快照
    - await engine.dispose() + 删除 -wal/-shm + 原子替换 + 清空 thumbs + init_db()
    """
    safe_name = Path(filename).name
    if not filename or safe_name != filename or not safe_name.lower().endswith(".db"):
        raise ValueError("非法的快照文件名")

    base_data = (data_dir if data_dir is not None else DATA_DIR).resolve()
    target_db = (
        db_path
        if db_path is not None
        else (base_data / "tsumugi.db" if data_dir is not None else DB_PATH)
    ).resolve()
    target_auto = (
        auto_dir
        if auto_dir is not None
        else (base_data / "backups" / "auto" if data_dir is not None else AUTO_BACKUPS_DIR)
    ).resolve()
    target_thumbs = (
        thumbs_dir
        if thumbs_dir is not None
        else (base_data / "thumbs" if data_dir is not None else THUMBS_DIR)
    ).resolve()
    legacy_thumbs = (base_data / "cache" / "thumbs").resolve() if data_dir is not None else THUMBS_CACHE_DIR.resolve()

    snapshot_file = (target_auto / safe_name).resolve()
    if not snapshot_file.is_relative_to(target_auto) or not snapshot_file.is_file():
        raise FileNotFoundError(f"找不到指定的数据库快照: {safe_name}")

    await asyncio.to_thread(
        verify_sqlite_integrity,
        snapshot_file,
        full=True,
        require_games_table=True,
    )

    safety_snapshot = await asyncio.to_thread(
        create_auto_snapshot,
        tag="pre_restore",
        force=True,
        db_path=target_db,
        auto_dir=target_auto,
    )

    await dispose_engine()

    def _swap_snapshot_sync() -> tuple[list[str], dict[str, int]]:
        removed_sidecars = _remove_sqlite_sidecars(target_db)
        _atomic_copy_file(snapshot_file, target_db)
        cleared_thumbs = clear_thumbnail_cache(
            thumbs_dir=target_thumbs,
            legacy_cache_dir=legacy_thumbs,
        )
        return removed_sidecars, cleared_thumbs

    removed_sidecars, cleared_thumbs = await asyncio.to_thread(_swap_snapshot_sync)
    await reinit_db()

    return {
        "restored": True,
        "filename": safe_name,
        "safety_snapshot": safety_snapshot["filename"] if safety_snapshot else None,
        "removed_sidecars": removed_sidecars,
        "cleared_thumbs": cleared_thumbs["deleted_files"],
    }
