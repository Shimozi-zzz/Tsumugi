# 0012 · PyInstaller 打包 transformers：精确收集尝试与已知限制

日期：2026-08-06
状态：部分成功（exe 可独立启动，embedding lazy-import 未解决，按止损点停止）

## 背景

Electron 打包后端（PyInstaller）遇到 transformers 的 `_LazyModule` 延迟导入
问题：打包后 `tsumugi-backend.exe` 可启动（health 200、connectors 正常），
但实际跑 embedding 检索时报：
`加载 embedding 模型失败：[WinError 3] 找不到
dist/.../_internal/transformers/models/__init__.pyc`。

## 诊断（已实测确认）

- `transformers/models/__init__.py` 用 `_LazyModule` 做延迟导入；
- `_LazyModule._get_module` 调 `importlib.import_module(".models.bert",
  "transformers")`，触发时 Python 需先加载 `transformers.models` 包；
- PyInstaller 默认把纯 Python 模块编译进 **PYZ 归档**（虚拟路径），
  `transformers.models` 在文件系统上不存在真实 `__init__.py`；
- `_LazyModule` 依赖 `__path__`（指向 `_internal/transformers/models`）做
  文件系统探测 → 找不到 `.pyc` 报错。
- PyInstaller 自带 `hook-transformers.py`，关键在它设置
  `module_collection_mode = 'pyz+py'`（源码 .py 落盘），但实测该机制
  未让 `transformers.models` 包在文件系统可用（仍报 .pyc 缺失）。

## 尝试过的方案与实测

| 方案 | entries | 打包耗时 | embedding 结果 |
| --- | --- | --- | --- |
| `collect_submodules("transformers")` 全量 | 4664 | ~20min+ | ✗ 同 .pyc 错误 |
| `collect_all("transformers")` | 4664+ | ~24min | ✗ 同 .pyc 错误 |
| **精确收集**（实测 47 个子模块）+ 复制 `models/__init__.py` 为数据 | 2418 | ~23min | ✗ 同 .pyc 错误 |

精确收集的实测触发清单（bge-small-zh-v1.5，含推理路径）：
`transformers.models.{bert, auto, align, bark, encoder_decoder}` + 顶层
`transformers.{AutoConfig, AutoModel, AutoTokenizer, T5Config, MT5Config,
generation, integrations, onnx, distributed}`。

## 停止原因（止损点）

按任务约定：打包问题最多重试 2 次。已尝试 3 种收集方案（全量/collect_all/
精确）均卡同一 `models/__init__.pyc` 错误，且每次重打包 20+ 分钟。
判断为 PyInstaller + transformers 4.57 的深层兼容问题（`module_collection_mode`
未覆盖子包），继续重打包性价比极低，**停止**。

## 已知限制与后续建议

- **当前打包产物**：`tsumugi-backend.exe` 可独立启动、health 200、
  connectors 发现正常，但 **embedding 不可用**（lazy import 失败）。
  对需要 embedding 的完整功能，该打包版不可用。
- 已锁定 numpy 1.26.4/scipy 1.11.4（解决 numpy 2.x 的
  "cannot load module more than once"），requirements.txt 已更新。
- 后续建议（未实施，留待专项）：
  1. 试用 `--collect-all transformers` 的官方 hook 组合（确认 hook 的
     `pyz+py` 是否需配合 `collect_submodules` 才能落盘子包）；
  2. 或改用 `pyinstaller-hooks-contrib` 更新版；
  3. 或降级 transformers 到 4.40 左右（PyInstaller 兼容更好的版本）；
  4. 或评估放弃 PyInstaller，改用 Nuitka/嵌入式 Python 等替代打包方案。
- 说明：onnxruntime/chromadb 打包本身正常；卡点仅在 transformers 的
  `_LazyModule`。Docker 方案（任务 1）不受影响，可正常分发。
