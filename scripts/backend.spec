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

# transformers 通过 _LazyModule 延迟导入，且 lazy import 依赖文件系统上真实存在的
# 模块源码（如 transformers/models/__init__.py）。pyinstaller-hooks-contrib 的
# hook-transformers.py 已设置 module_collection_mode='pyz+py'（源码 .py 落盘，且该
# 模式会**递归传播**到 transformers 所有子包），因此修复方案为：
#   1) 让 Analysis 把 transformers 及其 models 包作为**真实模块**收集——仅把
#      models/__init__.py 复制为数据文件无法让 frozen importer 找到 __init__.pyc
#      （见 docs/decisions/0012，曾因此 WinError 3 停止）；
#   2) 架构子包按 bge-small-zh-v1.5 实测触发清单精确收集，避免全量 4664 模块体积/耗时爆炸。
# 官方 hook 的 pyz+py 会把这些已收集模块同时落盘为源码，供 _LazyModule 解析。
transformers_model_pkgs = [
    "transformers.models.bert",
    "transformers.models.auto",
    "transformers.models.align",
    "transformers.models.bark",
    "transformers.models.encoder_decoder",
    "transformers.models.mt5",
    "transformers.models.t5",
]
# 包本身（__init__.py）必须作为模块收集，pyz+py 才会落盘其源码
hiddenimports += ["transformers", "transformers.models"] + transformers_model_pkgs
for _pkg in transformers_model_pkgs:
    hiddenimports += collect_submodules(_pkg)

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
    # 自定义 hook：覆盖 contrib 的 hook-transformers.py，把 transformers 收集模式改为
    # 'py'（纯源码 .py 落盘，frozen importer 直接加载源码）。transformers 的
    # define_import_structure() 用 glob 扫 models/**/*.py（'pyc' 只有 .pyc → KeyError
    # frozenset()），而 _LazyModule 又需磁盘可加载模块（contrib 'pyz+py' 的 importer
    # 查 __init__.pyc → WinError 3）。'py' 同时满足两者。详见 docs/decisions/0012。
    hookspath=[os.path.join(root, "scripts")],
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
