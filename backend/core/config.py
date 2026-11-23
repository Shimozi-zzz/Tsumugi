import os
import sys
from pathlib import Path

IS_FROZEN: bool = bool(getattr(sys, "frozen", False))
IS_WINDOWS: bool = sys.platform == "win32"

# 程序内置只读资源根路径（PyInstaller 冻结态指向 _MEIPASS，开发态指向仓库根目录）
BUNDLE_DIR: Path = (
    Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)).resolve()
    if IS_FROZEN
    else Path(__file__).resolve().parent.parent.parent
)
BASE_DIR: Path = BUNDLE_DIR

# 前端构建静态产物路径
FRONTEND_DIST_DIR: Path = BUNDLE_DIR / "frontend" / "dist"

# 用户可写数据目录
_env_data_dir = os.getenv("TSUMUGI_DATA_DIR", "").strip()
if _env_data_dir:
    DATA_DIR: Path = Path(_env_data_dir).expanduser().resolve()
elif IS_FROZEN:
    DATA_DIR = Path(sys.executable).resolve().parent / "data"
else:
    DATA_DIR = BUNDLE_DIR / "data"

APP_VERSION: str = os.getenv("TSUMUGI_VERSION", "0.9.0")
GITHUB_REPO: str = os.getenv("TSUMUGI_GITHUB_REPO", "Shimozi-zzz/Tsumugi")

DB_PATH: Path = DATA_DIR / "tsumugi.db"
SETTINGS_JSON_PATH: Path = DATA_DIR / "settings.json"
ASSETS_DIR: Path = DATA_DIR / "assets"
THUMBS_CACHE_DIR: Path = DATA_DIR / "cache" / "thumbs"
BACKUPS_DIR: Path = DATA_DIR / "backups"
WALLPAPERS_DIR: Path = DATA_DIR / "wallpapers"

DATABASE_URL: str = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"


def ensure_data_dirs() -> None:
    """确保所有本地可写数据子目录存在"""
    for directory in (DATA_DIR, ASSETS_DIR, THUMBS_CACHE_DIR, BACKUPS_DIR, WALLPAPERS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
