# PyInstaller spec - Tsumugi 后端可执行文件
# 用法：pyinstaller scripts/backend.spec
# 产物：dist/tsumugi-backend/tsumugi-backend.exe
# 说明：
# - app 包整体收集；sentence_transformers 模型在运行时下载（首次启动联网）
# - chromadb/onnxruntime 用 collect_all 确保隐藏依赖完整
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = os.path.abspath(os.path.join(os.getcwd()))

datas = []
binaries = []
hiddenimports = []

for pkg in ("chromadb", "onnxruntime", "sentence_transformers", "tokenizers"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# transformers 通过 _LazyModule 延迟导入，PyInstaller 静态分析不到且
# lazy import 依赖文件系统真实存在的 models/__init__.py。
# 方案：**精确收集** bge-small-zh-v1.5 实测触发的 models.* 子包
# （见 docs/decisions/0012-pyinstaller-transformers.md 的实测清单），
# 不用 collect_submodules("transformers") 全量收集（4664 entries 体积/耗时
# 爆炸）。models/__init__.py 显式复制为数据文件供 lazy import 触发。
transformers_model_pkgs = [
    "transformers.models.bert",
    "transformers.models.auto",
    "transformers.models.align",
    "transformers.models.bark",
    "transformers.models.encoder_decoder",
    "transformers.models.mt5",
    "transformers.models.t5",
]
for _pkg in transformers_model_pkgs:
    hiddenimports += collect_submodules(_pkg)
import transformers as _tf
datas += [(os.path.join(os.path.dirname(_tf.__file__), "models", "__init__.py"), "transformers/models")]

# Connector 插件通过运行时 iterdir 动态发现，静态分析看不到；
# 必须显式收集 app/connectors 整个目录（含 manifest.json 等数据文件）
# 和子模块，否则打包后 discover() 找不到目录。
# 注意：datas 相对路径基于 spec 所在目录（scripts/），须用 root 拼绝对路径。
datas += [(os.path.join(root, "app", "connectors"), "app/connectors")]
hiddenimports += [
    "app.connectors.base",
    "app.connectors.registry",
    "app.connectors.persistence",
    "app.connectors.ssrf",
    "app.connectors.bangumi.connector",
    "app.connectors.bangumi",
]

a = Analysis(
    ["../app/main.py"],
    pathex=[root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    # runtime hook：优先用 PyInstaller 注入的 SPECPATH，否则回退 cwd+scripts
    runtime_hooks=[os.path.join(globals().get("SPECPATH", os.path.abspath("scripts")), "pyi_rth_nltk_fix.py")],
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
    upx=False,  # UPX 压缩大二进制极慢，且 onnxruntime 已被 UPX 破坏，关闭
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="tsumugi-backend",
)
