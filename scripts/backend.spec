# PyInstaller spec - Tsumugi 后端可执行文件
# 用法：pyinstaller scripts/backend.spec
# 产物：dist/tsumugi-backend/tsumugi-backend.exe
# 说明：
# - app 包整体收集；sentence_transformers 模型在运行时下载（首次启动联网）
# - chromadb/onnxruntime 用 collect_all 确保隐藏依赖完整
import os

from PyInstaller.utils.hooks import collect_all

root = os.path.abspath(os.path.join(os.getcwd()))

datas = []
binaries = []
hiddenimports = []

for pkg in ("chromadb", "onnxruntime", "sentence_transformers", "tokenizers"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["../app/main.py"],
    pathex=[root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="tsumugi-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="tsumugi-backend",
)
