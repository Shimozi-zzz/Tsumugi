"""
Windows application core PyInstaller build script (packaged into Tsumugi-Setup-*.exe by Inno Setup).
Usage:
    cd frontend && npm ci && npm run build && cd ..
    uv sync --extra desktop
    uv run --extra desktop python packaging/build_windows.py
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
ENTRY_SCRIPT = ROOT_DIR / "desktop.py"
ICON_FILE = (ROOT_DIR / "packaging" / "tsumugi.ico").resolve()

HIDDEN_IMPORTS = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "aiosqlite",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    "pypinyin",
    "multipart",
    "python_multipart",
    "backend.api.import_external",
    "backend.services.importers",
    "backend.services.importers.base",
    "backend.services.importers.executor",
    "backend.services.importers.leveldb_reader",
    "backend.services.importers.litedb_v4",
    "backend.services.importers.playnite",
    "backend.services.importers.vnite",
    "cramjam",
]


def main() -> None:
    index_html = FRONTEND_DIST / "index.html"
    if not index_html.is_file():
        print(
            f"[ERROR] Frontend build output not found: {index_html}\n"
            "Run 'npm ci && npm run build' inside frontend/ first.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not ENTRY_SCRIPT.is_file():
        print(f"[ERROR] Desktop entry script not found: {ENTRY_SCRIPT}", file=sys.stderr)
        sys.exit(1)

    if not ICON_FILE.is_file():
        print(f"[ERROR] Application icon not found: {ICON_FILE}", file=sys.stderr)
        sys.exit(1)

    cmd: list[str] = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onedir",
        "--noconsole",
        "--noconfirm",
        "--clean",
        "--name",
        "Tsumugi",
        "--icon",
        str(ICON_FILE),
        "--add-data",
        f"{FRONTEND_DIST}{os.pathsep}frontend/dist",
        "--collect-data",
        "pypinyin",
        "--collect-all",
        "webview",
        "--collect-all",
        "clr_loader",
        "--collect-all",
        "pythonnet",
        "--collect-all",
        "cramjam",
    ]

    for mod in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", mod])

    cmd.append(str(ENTRY_SCRIPT))

    print("Building Windows app core bundle:", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT_DIR), check=True)

    output_dir = ROOT_DIR / "dist" / "Tsumugi"
    exe_name = "Tsumugi.exe" if sys.platform == "win32" else "Tsumugi"
    output_exe = output_dir / exe_name
    if not output_exe.is_file():
        print(f"[ERROR] Expected executable not found: {output_exe}", file=sys.stderr)
        sys.exit(1)

    bundled_frontend_candidates = (
        output_dir / "_internal" / "frontend" / "dist" / "index.html",
        output_dir / "frontend" / "dist" / "index.html",
    )
    bundled_index = next((p for p in bundled_frontend_candidates if p.is_file()), None)
    if bundled_index is None:
        print(
            "[ERROR] Bundled frontend/dist/index.html missing under dist/Tsumugi "
            "(checked _internal/frontend/dist/index.html and frontend/dist/index.html)",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[OK] Windows app core bundle ready for Inno Setup: {output_exe}")
    print(f"[OK] Verified bundled frontend entry: {bundled_index}")


if __name__ == "__main__":
    main()
