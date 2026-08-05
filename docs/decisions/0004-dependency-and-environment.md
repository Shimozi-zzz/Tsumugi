# 0004 · 依赖版本与本地运行环境（环境适配）

日期：2026-08-05
状态：已接受（Phase 1）

## 背景

原 `requirements.txt` 的固定版本在**本机（Windows，Python 3.14）**上无法安装：

- `pydantic-core 2.14.6`（pydantic 2.5.3 所需）：无 cp314 wheel，源码编译失败。
- `chroma-hnswlib 0.7.3`（chromadb 0.4.22/0.5.15 所需）：无 cp312/cp314
  Windows wheel，需要 MSVC 编译（本机无）。

## 决策

1. **运行时改为 Python 3.12**（本机同时装有 3.11–3.14，选 3.12 以获得最佳
   wheel 覆盖）。`.venv` 已用 Python 3.12 重建。
2. **依赖版本对齐到可安装、互不冲突的组合**（requirements.txt 已更新）：
   - `chromadb 0.4.22 → 1.0.13`：1.x 使用 Rust core，**不再依赖
     chroma-hnswlib**，且完整支持 pydantic v2（0.4.x 运行时与 pydantic v2
     冲突）。
   - `httpx 0.26 → 0.28.1`、`pydantic 2.5.3 → 2.10.4`、
     `pydantic-settings 2.1.0 → 2.6.1`、`fastapi 0.109 → 0.115.6`、
     `pytest 7.4.4 → 8.3.4`、`pytest-asyncio 0.23.3 → 0.24.0`。
   - Chroma 客户端 API（`PersistentClient` / `get_or_create_collection` /
     `query(where=...)`）在 1.x 保持兼容，业务代码无需因升级而改造。
3. **NLTK 安全钩子禁用**：NLTK 3.10+ 新增"阻止从 CWD 导入"的机制，但本项目
   `.venv` 位于项目目录内，导致 site-packages 里的 `regex` 等被误判为"CWD
   导入"而被阻止（`import sentence_transformers` 直接失败）。已通过
   `.venv/Lib/site-packages/sitecustomize.py` + `.env` 的
   `NLTK_DISABLE_IMPORT_SECURITY=1` 禁用（config.py 启动时 setdefault）。
4. **HuggingFace 镜像**：本机直连 huggingface.co 不通，模型通过
   `HF_ENDPOINT=https://hf-mirror.com` 下载（约 10s）。config.py 启动时
   setdefault 该变量，模型首用懒加载下载。

## 权衡

- 换 Python 3.12 而非适配 3.14：3.14 太新，部分科学计算库 wheel 不全，为
  阶段内稳定交付不值得投入。
- chroma 1.x 相比 0.5.x：API 兼容但内部实现（Rust core）差异较大，升级风险
  低（本项目只用最基础 add/query/delete）；换来零编译、零源码依赖。

## 已知简化

- `sitecustomize.py` 位于 `.venv` 内，不随仓库版本控制；换新环境需按本文档
  重建（或依赖 `.env` 的变量，二者任一生效即可）。
- 若在联网环境部署，可将 `HF_ENDPOINT` 改为官方域名。
