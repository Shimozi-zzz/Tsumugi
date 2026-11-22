import re
from pathlib import Path

from backend.schemas import BatchScanCandidate

# 常见干扰/辅助可执行程序黑名单（按小写子串或前缀匹配）
NOISE_EXE_KEYWORDS: tuple[str, ...] = (
    "unins000",
    "unins001",
    "unins002",
    "uninstall",
    "uninst",
    "unitycrashhandler",
    "crashhandler",
    "crashreporter",
    "crashpad",
    "dxsetup",
    "dxwebsetup",
    "vcredist",
    "vc_redist",
    "dotnet",
    "directx",
    "ue4prereq",
    "ueprereq",
    "physx",
    "openal",
    "redist",
    "setup",
    "installer",
    "install",
    "config",
    "configure",
    "settings",
    "setting",
    "option",
    "updater",
    "autoupdate",
    "update",
    "patcher",
    "repair",
    "register",
    "activation",
    "sysinfo",
    "cefprocess",
    "webhelper",
    "subprocess",
    "notification",
    "helper",
    "7z",
    "7za",
    "unrar",
    "ffmpeg",
    "ffprobe",
    "nodejs",
    "python",
    "siglusdebugger",
    "chm",
    "readme",
    "manual",
    "leproc",
    "legui",
)

SAVE_DIR_NAMES = {"save", "saves", "savedata", "save_data", "userdata", "user_data", "data_save"}
SCREENSHOT_DIR_NAMES = {"screenshot", "screenshots", "capture", "captures", "snap", "snaps", "cg"}

# 清理文件夹名中的常见发布组、版本与括号标签以提取干净搜索标题
_BRACKET_TAG_RE = re.compile(r"\[[^\]]*\]|【[^】]*】|\([^\)]*\)|（[^）]*）")
_VERSION_RE = re.compile(r"\b(?:v|ver\.?)\s*\d+(?:\.\d+)*\b", re.IGNORECASE)
_NOISE_SUFFIX_RE = re.compile(
    r"(?:汉化硬盘版|汉化版|中文硬盘版|中文版|免安装版|免安装|硬盘版|破解版|全CG存档|绿色版|高压版|完整版|正式版|简体中文|繁体中文|CHS|CHT|JPN|ENG|PC)$",
    re.IGNORECASE,
)


def clean_folder_title(folder_name: str) -> str:
    """从游戏目录名中去除发布组前缀、版本号等噪声，生成干净的游戏名"""
    cleaned = _BRACKET_TAG_RE.sub(" ", folder_name)
    cleaned = _VERSION_RE.sub(" ", cleaned)
    cleaned = re.sub(r"[_+]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_.~")
    prev = None
    while prev != cleaned:
        prev = cleaned
        cleaned = _NOISE_SUFFIX_RE.sub("", cleaned).strip(" -_.~")
    return cleaned or folder_name


def is_noise_exe(exe_path: Path) -> bool:
    """判断某个 .exe 是否属于卸载器、崩溃上报、运行库安装器或配置工具等干扰程序"""
    stem = exe_path.stem.lower()
    name = exe_path.name.lower()
    for kw in NOISE_EXE_KEYWORDS:
        if kw == stem or kw in name:
            return True
    return False


def _score_exe_candidate(exe_path: Path, folder: Path, clean_title: str) -> float:
    score = 0.0
    # 位于游戏根目录的优先级高于子目录
    depth = len(exe_path.relative_to(folder).parts)
    if depth == 1:
        score += 50.0
    elif depth == 2:
        score += 20.0

    # 与目录名 / 清理标题相似加分
    stem_l = exe_path.stem.lower()
    title_l = clean_title.lower()
    folder_l = folder.name.lower()
    if stem_l in title_l or title_l in stem_l or stem_l in folder_l:
        score += 35.0
    if stem_l in ("game", "start", "play", "main", "bgi", "siglusengine", "krkr", "cmvs", "realive", "advhd", "ethornell"):
        score += 25.0

    # 适中大小的主程序通常比小工具大（加权上限 30 分）
    try:
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        score += min(size_mb * 2.0, 30.0)
    except OSError:
        pass

    return score


def _collect_exes(folder: Path) -> list[Path]:
    """扫描一级目录与常见二级子目录中的 .exe 文件"""
    found: list[Path] = []
    try:
        for item in folder.iterdir():
            if item.is_file() and item.suffix.lower() == ".exe":
                found.append(item)
            elif item.is_dir() and not item.name.startswith("."):
                # 仅向下扫描一层子目录，避免遍历庞大资源目录卡顿
                try:
                    for sub in item.iterdir():
                        if sub.is_file() and sub.suffix.lower() == ".exe":
                            found.append(sub)
                except OSError:
                    continue
    except OSError:
        return []
    return found


def _detect_special_dirs(folder: Path) -> tuple[str, str]:
    save_dir = ""
    ss_dir = ""
    try:
        for item in folder.iterdir():
            if not item.is_dir():
                continue
            low = item.name.lower()
            if not save_dir and low in SAVE_DIR_NAMES:
                save_dir = str(item)
            if not ss_dir and low in SCREENSHOT_DIR_NAMES:
                ss_dir = str(item)
    except OSError:
        pass
    return save_dir, ss_dir


def scan_game_directory(
    root_dir: str,
    existing_exes: set[str] | None = None,
    existing_titles: set[str] | None = None,
) -> list[BatchScanCandidate]:
    """
    遍历目标根目录的一级子文件夹，自动过滤干扰 .exe 并推举游戏主程序、存档目录与截图目录。
    """
    root = Path(root_dir.strip())
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"指定的扫描目录不存在或不是文件夹: {root_dir}")

    norm_exes = {e.lower().replace("\\", "/") for e in (existing_exes or set()) if e}
    norm_titles = {t.lower().strip() for t in (existing_titles or set()) if t}

    candidates: list[BatchScanCandidate] = []
    subdirs = sorted(
        (d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")),
        key=lambda p: p.name.lower(),
    )

    for folder in subdirs:
        title = clean_folder_title(folder.name)
        all_exes = _collect_exes(folder)
        clean_exes = [exe for exe in all_exes if not is_noise_exe(exe)]

        # 如果所有 exe 都被过滤了（罕见情况），回退保留原始 exe 列表供用户手动挑选
        usable = clean_exes if clean_exes else all_exes
        usable.sort(key=lambda p: _score_exe_candidate(p, folder, title), reverse=True)

        suggested = str(usable[0]) if usable else ""
        save_dir, ss_dir = _detect_special_dirs(folder)

        norm_suggested = suggested.lower().replace("\\", "/")
        already = (
            (bool(norm_suggested) and norm_suggested in norm_exes)
            or (title.lower().strip() in norm_titles)
            or (folder.name.lower().strip() in norm_titles)
        )

        candidates.append(
            BatchScanCandidate(
                folder_name=folder.name,
                folder_path=str(folder),
                clean_title=title,
                suggested_exe=suggested,
                candidate_exes=[str(p) for p in usable[:12]],
                detected_save_dir=save_dir,
                detected_screenshot_dir=ss_dir,
                already_imported=already,
            )
        )

    return candidates
