"""
Windows 绿色便携版 PyInstaller 打包脚本
用法：
    cd frontend && npm ci && npm run build && cd ..
    uv sync --extra desktop
    uv run --extra desktop python packaging/build_windows.py
产物：
    dist/Tsumugi/Tsumugi.exe（便携数据默认写入同级 data/ 目录）
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
ENTRY_SCRIPT = ROOT_DIR / "desktop.py"

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
]


def main() -> None:
    index_html = FRONTEND_DIST / "index.html"
    if not index_html.is_file():
        print(
            f"[ERROR] 未找到前端构建产物：{index_html}\n"
            "请先在 frontend/ 目录执行 npm ci && npm run build。",
            file=sys.stderr,
        )
        sys.exit(1)

    if not ENTRY_SCRIPT.is_file():
        print(f"[ERROR] 未找到桌面入口脚本：{ENTRY_SCRIPT}", file=sys.stderr)
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
        "--add-data",
        f"{FRONTEND_DIST}{os.pathsep}frontend/dist",
        "--collect-data",
        "pypinyin",
        "--collect-submodules",
        "webview",
    ]

    for mod in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", mod])

    cmd.append(str(ENTRY_SCRIPT))

    print("Running PyInstaller:", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT_DIR), check=True)

    output_dir = ROOT_DIR / "dist" / "Tsumugi"
    exe_name = "Tsumugi.exe" if sys.platform == "win32" else "Tsumugi"
    output_exe = output_dir / exe_name
    if not output_exe.exists():
        print(f"[ERROR] 打包完成但未找到预期可执行文件：{output_exe}", file=sys.stderr)
        sys.exit(1)

    print(f"[OK] 便携版打包完成：{output_exe}")


if __name__ == "__main__":
    main()
