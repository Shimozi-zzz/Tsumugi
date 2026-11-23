from __future__ import annotations

from datetime import datetime, timezone
import html
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from backend.services.importers.base import (
    BaseLibraryImporter,
    DetectResult,
    ExternalGameCandidate,
    ImporterError,
)
from backend.services.importers.litedb_v4 import read_litedb_v4_documents

logger = logging.getLogger("tsumugi.services.importers.playnite")

PLAYNITE_STEAM_PLUGIN_ID = "cb91dfc9-b977-43bf-8e70-55f46e410fab"

DICTIONARY_TABLES: tuple[tuple[str, str], ...] = (
    ("platforms", "platforms.db"),
    ("companies", "companies.db"),
    ("genres", "genres.db"),
    ("tags", "tags.db"),
    ("sources", "sources.db"),
    ("completionstatuses", "completionstatuses.db"),
)

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_BLOCK_BREAK_RE = re.compile(r"<(?:br\s*/?|/p|/div|/li|/h[1-6]|tr)[^>]*>", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_INSTALL_DIR_VAR_RE = re.compile(r"\{InstallDir\}", re.IGNORECASE)

_STEAM_URL_RE = re.compile(r"store\.steampowered\.com/app/(\d+)", re.IGNORECASE)
_VNDB_URL_RE = re.compile(r"vndb\.org/(v\d+)", re.IGNORECASE)
_BGM_URL_RE = re.compile(r"(?:bgm\.tv|bangumi\.tv|chii\.in)/subject/(\d+)", re.IGNORECASE)


def clean_html_description(raw: str | None) -> str:
    """清洗 Playnite 富文本 HTML 简介，保留段落换行并反转义实体字符"""
    if not raw:
        return ""
    text = str(raw)
    text = _SCRIPT_STYLE_RE.sub("", text)
    text = _BLOCK_BREAK_RE.sub("\n", text)
    text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    cleaned = "\n".join(lines).strip()
    return _MULTI_NEWLINE_RE.sub("\n\n", cleaned)


def _normalize_guid(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip().lower()
    if s in ("", "00000000-0000-0000-0000-000000000000"):
        return ""
    return s


def _parse_datetime(val: Any) -> datetime | None:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, (int, float)):
        try:
            # 秒或毫秒时间戳兼容
            ts = float(val) / 1000.0 if abs(float(val)) > 1e11 else float(val)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(val, str):
        raw = val.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(raw[:19], fmt)
                except ValueError:
                    continue
    return None


def _parse_release_date(val: Any) -> str:
    if val is None or val == "":
        return ""
    if isinstance(val, dict):
        # Playnite 10 ReleaseDate struct: {"ReleaseDate": "2020-05-01"} 或 {"Year": 2020, "Month": 5, "Day": 1}
        inner = val.get("ReleaseDate") or val.get("releaseDate")
        if inner:
            return _parse_release_date(inner)
        year = val.get("Year") or val.get("year")
        month = val.get("Month") or val.get("month")
        day = val.get("Day") or val.get("day")
        if year:
            if month and day:
                return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
            if month:
                return f"{int(year):04d}-{int(month):02d}"
            return f"{int(year):04d}"
        return ""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    if len(s) >= 10 and re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    if re.match(r"^\d{4}(-\d{2})?$", s):
        return s
    return s[:32]


def _map_completion_status(status_name: str, playtime_seconds: int) -> str:
    low = (status_name or "").strip().lower()
    if any(k in low for k in ("completed", "beaten", "finished", "通关", "已完成", "玩过", "完成")):
        return "done"
    if any(k in low for k in ("playing", "in progress", "游玩中", "攻略中", "在玩")):
        return "playing"
    if any(k in low for k in ("not played", "plan to play", "on hold", "abandoned", "未开始", "未玩", "想玩", "搁置")):
        return "todo"
    return "playing" if playtime_seconds > 0 else "todo"


def _expand_install_dir(raw_path: str, install_dir: str) -> str:
    path_str = (raw_path or "").strip()
    if not path_str:
        return ""
    if not _INSTALL_DIR_VAR_RE.search(path_str):
        return path_str
    clean_install = (install_dir or "").strip().rstrip("\\/")
    if not clean_install:
        return _INSTALL_DIR_VAR_RE.sub("", path_str).lstrip("\\/")
    expanded = _INSTALL_DIR_VAR_RE.sub(lambda _: clean_install, path_str)
    # 避免替换后产生双分隔符（保留 Windows UNC 前缀 \\）
    if expanded.startswith("\\\\"):
        return "\\\\" + re.sub(r"[\\/]{2,}", "\\\\", expanded[2:])
    sep = "\\" if "\\" in clean_install else "/"
    return re.sub(r"[\\/]{2,}", lambda _: sep, expanded)


def _extract_executable_path(doc: dict[str, Any], install_dir: str) -> str:
    actions = doc.get("GameActions") or doc.get("gameActions") or []
    if not isinstance(actions, list):
        return ""

    # ActionType: 0 = File, 1 = URL, 2 = Emulator
    scored: list[tuple[int, str]] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        raw_path = str(action.get("Path") or action.get("path") or "").strip()
        if not raw_path:
            continue
        action_type = action.get("Type")
        is_play = bool(action.get("IsPlayAction", False))
        is_file = action_type in (0, "File", "file", None)
        is_url = action_type in (1, "URL", "Url", "url")

        expanded = _expand_install_dir(raw_path, install_dir)
        if is_file and is_play:
            scored.append((0, expanded))
        elif is_file:
            scored.append((1, expanded))
        elif is_url and is_play:
            scored.append((2, expanded))
        elif is_url:
            scored.append((3, expanded))

    if not scored:
        return ""
    scored.sort(key=lambda item: item[0])
    return scored[0][1]


def _resolve_media_file(raw_ref: Any, library_dir: Path) -> str:
    ref = str(raw_ref or "").strip()
    if not ref:
        return ""
    low = ref.lower()
    if low.startswith(("http://", "https://")):
        return ""

    # 1. 尝试相对 library/files/ 解析（将 Windows 反斜杠统一转为 Path 分段）
    rel_parts = [p for p in ref.replace("\\", "/").split("/") if p and p != "."]
    if rel_parts:
        candidate = library_dir / "files" / Path(*rel_parts)
        if candidate.is_file():
            return str(candidate.resolve())

        # 兼容直接指向 library 下相对路径
        direct_rel = library_dir / Path(*rel_parts)
        if direct_rel.is_file():
            return str(direct_rel.resolve())

    # 2. 尝试作为绝对本地路径解析
    abs_path = Path(ref)
    if abs_path.is_file():
        return str(abs_path.resolve())

    return ""


def _extract_ids_from_links(links: Any) -> tuple[str, str, str]:
    steam_id = ""
    vndb_id = ""
    bgm_id = ""
    if not isinstance(links, list):
        return steam_id, vndb_id, bgm_id

    for item in links:
        url = ""
        if isinstance(item, dict):
            url = str(item.get("Url") or item.get("url") or "").strip()
        elif isinstance(item, str):
            url = item.strip()
        if not url:
            continue

        if not steam_id:
            m = _STEAM_URL_RE.search(url)
            if m:
                steam_id = m.group(1)
        if not vndb_id:
            m = _VNDB_URL_RE.search(url)
            if m:
                vndb_id = m.group(1).lower()
        if not bgm_id:
            m = _BGM_URL_RE.search(url)
            if m:
                bgm_id = m.group(1)

    return steam_id, vndb_id, bgm_id


def _load_json_dir_documents(folder: Path) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    if not folder.is_dir():
        return docs
    for jf in sorted(folder.glob("*.json")):
        try:
            data = json.loads(jf.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                docs.append(data)
        except Exception as exc:
            logger.debug("Skipping invalid Playnite JSON file %s: %s", jf, exc)
    return docs


def _resolve_playnite_library_dir(raw_path: str) -> Path:
    """
    智能解析用户提供的 Playnite 路径：
    支持直接传入 library 目录、Playnite 根/便携目录（含 library/ 或 config.json）、或 games.db 文件路径。
    """
    p = Path(raw_path).expanduser()
    if p.is_file():
        if p.name.lower() == "config.json":
            configured = _read_database_path_from_config(p)
            if configured and configured.exists():
                return configured
        p = p.parent

    if not p.exists():
        raise ImporterError(f"指定的 Playnite 路径不存在: {raw_path}")

    # 直接就是 library 目录（含 games.db 或 games/）
    if (p / "games.db").is_file() or (p / "games").is_dir():
        return p.resolve()

    # 用户传入的是 Playnite 安装/配置根目录（含 config.json 或 library/）
    cfg = p / "config.json"
    if cfg.is_file():
        configured = _read_database_path_from_config(cfg)
        if configured and ((configured / "games.db").is_file() or (configured / "games").is_dir()):
            return configured.resolve()

    lib_sub = p / "library"
    if (lib_sub / "games.db").is_file() or (lib_sub / "games").is_dir():
        return lib_sub.resolve()

    raise ImporterError(
        f"在目录 {p} 中未找到 Playnite 游戏库（缺少 games.db 或 Playnite 9 的 games/*.json 目录）"
    )


def _read_database_path_from_config(config_file: Path) -> Path | None:
    try:
        cfg = json.loads(config_file.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(cfg, dict):
        return None
    db_path = str(cfg.get("DatabasePath") or "").strip()
    if not db_path:
        return None
    # 兼容 Playnite 便携版变量 {PlayniteDir}
    if "{playnitedir}" in db_path.lower():
        playnite_dir_str = str(config_file.parent)
        db_path = re.sub(r"\{PlayniteDir\}", lambda _: playnite_dir_str, db_path, flags=re.IGNORECASE)
    candidate = Path(db_path).expanduser()
    if not candidate.is_absolute():
        candidate = config_file.parent / candidate
    return candidate


def _is_valid_playnite_library(path: Path) -> bool:
    if not path.is_dir():
        return False
    if (path / "games.db").is_file():
        return True
    games_dir = path / "games"
    if games_dir.is_dir() and any(games_dir.glob("*.json")):
        return True
    return False


class PlayniteImporter(BaseLibraryImporter):
    """Playnite 游戏库导入适配器（支持 Playnite 10+ LiteDB v4 与 Playnite 9 JSON 目录）"""

    source_name = "playnite"

    def detect_path(self) -> DetectResult:
        candidates: list[Path] = []
        appdata = os.environ.get("APPDATA", "").strip()

        if appdata:
            playnite_root = Path(appdata) / "Playnite"
            cfg_file = playnite_root / "config.json"
            if cfg_file.is_file():
                configured = _read_database_path_from_config(cfg_file)
                if configured:
                    candidates.append(configured)
            candidates.append(playnite_root / "library")

        # 兜底常见路径
        home = Path.home()
        default_win_lib = home / "AppData" / "Roaming" / "Playnite" / "library"
        if default_win_lib not in candidates:
            candidates.append(default_win_lib)

        unique_candidates: list[str] = []
        seen: set[str] = set()
        for c in candidates:
            s = str(c)
            if s not in seen:
                seen.add(s)
                unique_candidates.append(s)

        for c in candidates:
            if _is_valid_playnite_library(c):
                fmt = "LiteDB (games.db)" if (c / "games.db").is_file() else "Playnite 9 JSON"
                return DetectResult(
                    source="playnite",
                    detected_path=str(c.resolve()),
                    valid=True,
                    message=f"已自动探测到 Playnite 游戏库（{fmt}）",
                    candidates=unique_candidates,
                )

        fallback_hint = unique_candidates[0] if unique_candidates else ""
        return DetectResult(
            source="playnite",
            detected_path=fallback_hint,
            valid=False,
            message="未在默认目录探测到 Playnite 游戏库，请手动指定 library 目录或便携版目录",
            candidates=unique_candidates,
        )

    def scan(self, path: str) -> list[ExternalGameCandidate]:
        raw = (path or "").strip()
        if not raw:
            raise ImporterError("请先填写或探测 Playnite 游戏库路径")

        library_dir = _resolve_playnite_library_dir(raw)
        games_db_path = library_dir / "games.db"
        games_json_dir = library_dir / "games"

        if games_db_path.is_file():
            raw_games, dicts = self._read_litedb_snapshot(library_dir)
        elif games_json_dir.is_dir():
            raw_games, dicts = self._read_playnite9_json(library_dir)
        else:
            raise ImporterError(f"在目录 {library_dir} 中未找到 games.db 或 games/*.json")

        candidates: list[ExternalGameCandidate] = []
        for doc in raw_games:
            cand = self._map_game_doc(doc, dicts, library_dir)
            if cand is not None:
                candidates.append(cand)

        candidates.sort(key=lambda item: (item.name.lower(), item.external_id))
        return candidates

    def _read_litedb_snapshot(
        self,
        library_dir: Path,
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
        """
        将 games.db 及全部字典表先只读复制到 tempfile.TemporaryDirectory 再解析，
        彻底避免触发 Playnite 运行时的文件锁冲突。
        """
        dicts: dict[str, dict[str, str]] = {name: {} for name, _ in DICTIONARY_TABLES}

        with tempfile.TemporaryDirectory(prefix="tsumugi_playnite_") as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            src_games = library_dir / "games.db"
            dst_games = tmp_dir / "games.db"
            try:
                shutil.copy2(src_games, dst_games)
            except OSError as exc:
                raise ImporterError(f"复制 Playnite games.db 失败，请检查文件权限: {exc}") from exc

            raw_games = read_litedb_v4_documents(dst_games)

            for table_key, db_filename in DICTIONARY_TABLES:
                src_dict = library_dir / db_filename
                if not src_dict.is_file():
                    continue
                dst_dict = tmp_dir / db_filename
                try:
                    shutil.copy2(src_dict, dst_dict)
                    rows = read_litedb_v4_documents(dst_dict)
                    mapping: dict[str, str] = {}
                    for row in rows:
                        rid = _normalize_guid(row.get("_id") or row.get("Id") or row.get("id"))
                        rname = str(row.get("Name") or row.get("name") or "").strip()
                        if rid and rname:
                            mapping[rid] = rname
                    dicts[table_key] = mapping
                except Exception as exc:
                    logger.warning("Failed reading Playnite dictionary %s: %s", db_filename, exc)

        return raw_games, dicts

    def _read_playnite9_json(
        self,
        library_dir: Path,
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
        """兼容读取 Playnite 9 的 library/games/*.json 与字典子目录"""
        raw_games = _load_json_dir_documents(library_dir / "games")
        dicts: dict[str, dict[str, str]] = {}
        for table_key, _ in DICTIONARY_TABLES:
            mapping: dict[str, str] = {}
            for row in _load_json_dir_documents(library_dir / table_key):
                rid = _normalize_guid(row.get("Id") or row.get("_id") or row.get("id"))
                rname = str(row.get("Name") or row.get("name") or "").strip()
                if rid and rname:
                    mapping[rid] = rname
            dicts[table_key] = mapping
        return raw_games, dicts

    def _map_game_doc(
        self,
        doc: dict[str, Any],
        dicts: dict[str, dict[str, str]],
        library_dir: Path,
    ) -> ExternalGameCandidate | None:
        name = str(doc.get("Name") or doc.get("name") or "").strip()
        if not name:
            return None

        ext_id = _normalize_guid(doc.get("_id") or doc.get("Id") or doc.get("id"))
        if not ext_id:
            ext_id = f"playnite:{name.lower()}"

        def _lookup_ids(id_list: Any, table_key: str) -> list[str]:
            if not isinstance(id_list, list):
                return []
            table = dicts.get(table_key, {})
            out: list[str] = []
            for raw_id in id_list:
                gid = _normalize_guid(raw_id)
                resolved = table.get(gid)
                if resolved and resolved not in out:
                    out.append(resolved)
            return out

        developers = _lookup_ids(doc.get("DeveloperIds") or doc.get("developerIds"), "companies")
        publishers = _lookup_ids(doc.get("PublisherIds") or doc.get("publisherIds"), "companies")
        genres = _lookup_ids(doc.get("GenreIds") or doc.get("genreIds"), "genres")
        tags = _lookup_ids(doc.get("TagIds") or doc.get("tagIds"), "tags")
        platforms = _lookup_ids(doc.get("PlatformIds") or doc.get("platformIds"), "platforms")

        # 合并 genres 与 tags 去重
        merged_tags: list[str] = []
        seen_tags: set[str] = set()
        for t in [*genres, *tags]:
            low = t.lower()
            if low not in seen_tags:
                seen_tags.add(low)
                merged_tags.append(t)

        source_id = _normalize_guid(doc.get("SourceId") or doc.get("sourceId"))
        source_name = dicts.get("sources", {}).get(source_id, "")

        completion_id = _normalize_guid(doc.get("CompletionStatusId") or doc.get("completionStatusId"))
        completion_name = dicts.get("completionstatuses", {}).get(completion_id, "")

        raw_playtime = doc.get("Playtime")
        if raw_playtime is None:
            raw_playtime = doc.get("playtime", 0)
        try:
            playtime_seconds = max(0, int(raw_playtime or 0))
        except (TypeError, ValueError):
            playtime_seconds = 0

        last_played = _parse_datetime(doc.get("LastActivity") or doc.get("lastActivity"))
        release_date = _parse_release_date(doc.get("ReleaseDate") or doc.get("releaseDate"))
        description = clean_html_description(doc.get("Description") or doc.get("description"))

        install_dir = str(doc.get("InstallDirectory") or doc.get("installDirectory") or "").strip()
        executable_path = _extract_executable_path(doc, install_dir)

        cover_path = _resolve_media_file(doc.get("CoverImage") or doc.get("coverImage"), library_dir)
        background_path = _resolve_media_file(
            doc.get("BackgroundImage") or doc.get("backgroundImage"), library_dir
        )

        # Steam / VNDB / Bangumi 外部 ID 提取
        plugin_id = _normalize_guid(doc.get("PluginId") or doc.get("pluginId"))
        game_id_str = str(doc.get("GameId") or doc.get("gameId") or "").strip()
        link_steam, link_vndb, link_bgm = _extract_ids_from_links(doc.get("Links") or doc.get("links"))

        steam_appid = ""
        if plugin_id == PLAYNITE_STEAM_PLUGIN_ID and game_id_str.isdigit():
            steam_appid = game_id_str
        elif link_steam:
            steam_appid = link_steam

        platform_source = source_name or (platforms[0] if platforms else "")
        if not platform_source and steam_appid:
            platform_source = "Steam"
        if not platform_source:
            platform_source = "Playnite"

        return ExternalGameCandidate(
            external_id=ext_id,
            source_app="playnite",
            name=name,
            original_name=str(doc.get("SortingName") or "").strip()
            if str(doc.get("SortingName") or "").strip().lower() != name.lower()
            else "",
            description=description,
            release_date=release_date,
            developers=developers,
            publishers=publishers,
            tags=merged_tags,
            playtime_seconds=playtime_seconds,
            last_played_at=last_played,
            play_status=_map_completion_status(completion_name, playtime_seconds),
            platform_source=platform_source,
            steam_appid=steam_appid,
            vndb_id=link_vndb,
            bangumi_id=link_bgm,
            install_dir=install_dir,
            executable_path=executable_path,
            cover_path=cover_path,
            background_path=background_path,
        )
