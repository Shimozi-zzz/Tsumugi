# PyInstaller 自定义 hook：覆盖 pyinstaller-hooks-contrib 的 hook-transformers.py。
#
# 变更点：module_collection_mode = 'py'（contrib 默认 'pyz+py'）。
#
# 原因（实测两次，见 docs/decisions/0012）：
# transformers 依赖两个文件系统前提，二者必须同时满足：
#   1) `transformers/__init__.py` 用 `define_import_structure()` **glob 扫描**
#      models/**/*.py 源码构建 _LazyModule 结构 → 磁盘必须存在 .py 源码；
#   2) `_LazyModule` 通过 __path__ 探测加载子模块 → 磁盘必须存在可被 frozen
#      importer 加载的模块文件。
# 实测：
#   - 'pyc'（仅编译 .pyc 落盘）→ 前提 1 不满足 → KeyError: frozenset()
#     （扫描不到 .py）；
#   - 'pyz+py'（contrib，PYZ + .py 落盘）→ 前提 2 的 importer 仍查 __init__.pyc
#     → WinError 3。
#   - 'py'（纯源码 .py 落盘，frozen importer 直接加载源码，PyInstaller
#     pyimod02_importers 明确支持 source-only 模块）→ 两个前提同时满足。
#
# 依赖 metadata 收集逻辑与 contrib hook 保持一致（运行时版本查询需要）。
from PyInstaller.utils.hooks import (
    copy_metadata,
    get_module_attribute,
    is_module_satisfies,
)

datas = []
hiddenimports = []

try:
    dependencies = get_module_attribute(
        'transformers.dependency_versions_table',
        'deps',
    )
except Exception:
    dependencies = {}

for dependency_name, dependency_req in dependencies.items():
    if not is_module_satisfies(dependency_req):
        continue
    try:
        datas += copy_metadata(dependency_name)
    except Exception:
        pass

# 关键：transformers 需以纯源码 .py 落盘（既供目录扫描，也供 importer 源码加载）
module_collection_mode = 'py'
