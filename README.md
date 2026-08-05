# Tsumugi（紬）— 个人知识图书馆

一个**本地优先**的个人知识管理系统：导入你的笔记/文档/图片，用语义检索找到相关内容，并基于检索结果与 LLM 对话。支持接入外部数据源（如 Bangumi），把感兴趣的资料"收藏入库"参与检索。

> 「紬（tsumugi）」意为手工织出的绸缎——把零散的资料织成属于你自己的知识体系。

---

## 特性

- **本地 RAG 核心**：文档导入 → 切分 → 向量化 → 语义检索 → prompt 拼接 → LLM 流式回答，核心逻辑全部手写，不依赖 LangChain 等封装框架（实现透明、可逐层讲解）。
- **多内容类型**：Markdown/纯文本笔记 + 图片（附件存储，不切分）。
- **标签系统**：标签筛选（任一/全部命中）、重命名/合并/删除。
- **外部数据源**：
  - 内置 Bangumi Connector（搜索/详情/收藏入库）；
  - **声明式自定义数据源**（Phase 4）：只需配置 HTTP 端点 + 字段映射即可接入，无需写代码、不执行任意代码（安全边界）。
  - **联合检索**：本地向量检索 + 已启用外部源结果合并，单源失败自动降级。
- **Web + 桌面双形态**：浏览器访问，或 Electron 客户端（自动管理后端，与 Web 共享同一数据）。
- **UI 自定义**：6 套主题（默认/书斋/春/夏/秋/冬）+ 仪表盘面板增删。
- **流式回答**：SSE 实时输出。

---

## 架构

```
┌──────────────────────────────────────────────┐
│  表现层：React + Tailwind（主题/布局可自定义）    │
│            Web (Vite)  │  Electron 客户端       │
└───────────────┬──────────────────────────────┘
                │ REST / SSE
┌───────────────▼──────────────────────────────┐
│  API 层：FastAPI 路由                          │
├──────────────────────────────────────────────┤
│  检索编排：本地向量检索 + 已启用 Connector 联合     │
├──────────────────────────────────────────────┤
│  RAG 核心：prompt 拼接 + DeepSeek API（手写）    │
├──────────────────────────────────────────────┤
│  Connector 插件层：统一接口 + 内置 Bangumi +      │
│                 声明式自定义数据源                 │
├──────────────────────────────────────────────┤
│  数据层：SQLite（元数据）+ Chroma（向量）          │
└──────────────────────────────────────────────┘
```

### 核心流程

```
导入文档 → 切分(chunk) → bge embedding → 写入 Chroma + SQLite
  提问   → 查询 embedding → Chroma 语义检索(+标签过滤) → 去重排序
  回答   → 检索结果拼接 prompt → DeepSeek API → SSE 流式输出
```

---

## 快速开始

### 环境要求

- Python 3.12（本项目在 Windows + Python 3.12 上开发验证）
- Node.js 20+
- （可选）Docker，用于容器化部署

### 1. 配置

```bash
copy .env.example .env        # Windows
cp .env.example .env          # Linux/macOS
```

编辑 `.env`，填入真实值：

| 变量 | 说明 |
| --- | --- |
| `DEEPSEEK_API_KEY` | **必填**，DeepSeek 平台 API Key |
| `HF_ENDPOINT` | HuggingFace 模型下载端点（默认 `https://hf-mirror.com`，国内镜像） |

其余（`CHUNK_SIZE`、`TOP_K`、`MAX_CONTEXT_LENGTH`、端口等）有默认值，可按需调整。

### 2. 安装依赖

```bash
# 后端
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt

# 前端
cd frontend
npm install
```

> Windows 注意：首次提问会触发 embedding 模型下载（约 10s，走 HF 镜像）。

### 3. 运行

**方式一：一键启动（推荐）**

```bash
start.bat          # Web 模式：后端 + 浏览器
start.bat electron # 客户端模式：Electron（自动管理后端）
```

**方式二：手动**

```bash
# 后端（终端 1）
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8001

# 前端（终端 2）
cd frontend && npm run dev
# 打开 http://localhost:5173
```

### 4. 使用

1. **导入**：上传 `.md/.txt` 或图片，可打标签；重复内容自动跳过（`force` 可强制）。
2. **提问**：输入问题，SSE 流式回答，回答下方显示参考来源。
3. **筛选**：按标签（任一/全部）、类型筛选已入库资料。
4. **外部源**：调用 `POST /api/connectors` 接入声明式数据源后，联合检索会包含外部结果。

---

## 测试

```bash
pytest -q          # 102 个用例，覆盖率 82%（门槛 70%）
```

覆盖：切分策略、检索排序/去重、标签过滤、prompt 拼接、Connector normalize、
声明式数据源、API 接口（embedding/LLM/向量库全部 mock，秒级跑完）。

CI（GitHub Actions）：后端 pytest + 覆盖率，前端 build。

---

## 目录结构

```
Tsumugi/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置（pydantic-settings）
│   ├── database.py          # SQLAlchemy 引擎/会话/轻量迁移
│   ├── models.py            # Item/Chunk/Tag/Source
│   ├── schemas.py           # Pydantic schema
│   ├── embeddings.py        # embedding 模型懒加载单例
│   ├── vectorstore.py       # Chroma 封装
│   ├── ingest.py            # 切分 + 入库 + 去重 + 删除
│   ├── retrieval.py         # 向量检索 + 标签过滤 + 排序去重
│   ├── rag.py               # prompt 拼接 + DeepSeek 流式
│   ├── connectors/          # Connector 插件层
│   │   ├── base.py          # 统一接口 + 声明式 Connector
│   │   ├── registry.py      # 注册/发现
│   │   ├── persistence.py   # 声明式配置持久化
│   │   └── bangumi/         # 内置 Bangumi 实现
│   └── api/routes.py        # API 路由
├── frontend/                # React + Tailwind（Vite）
│   ├── src/
│   │   ├── App.jsx          # 主界面（主题/布局/面板）
│   │   ├── themes.js        # 主题系统
│   │   ├── layout.js        # 仪表盘布局
│   │   └── components/Panel.jsx
│   └── electron/            # Electron 客户端
├── tests/                   # pytest（102 用例）
├── docs/decisions/          # ADR-lite 决策记录（0001-0009）
├── Dockerfile / docker-compose.yml / nginx.conf
├── start.bat                # 一键启动
└── .env.example
```

---

## RAG 原理速览（面试可用）

1. **切分**：段落/标题感知的贪心打包，`chunk_size=512`、`overlap=64`，超大块按句子边界硬切（决策 0001）。
2. **向量化**：`BAAI/bge-small-zh-v1.5` 生成 512 维归一化向量，存 Chroma（cosine 距离）。
3. **检索**：查询向量在 Chroma 检索 → 内容去重 + 按条目去重（`max_chunks_per_item`）→ 标签过滤先 SQL 筛 ids 再作向量 `where`（决策 0002）。
4. **Prompt**：system（只依据资料/不编造/标注来源）+ 按相关度顺序的参考资料（累计字符预算截断）+ 问题（决策 0003）。
5. **生成**：DeepSeek API SSE 流式输出，超时/限流/鉴权映射为友好错误。

---

## 技术栈

| 模块 | 选型 |
| --- | --- |
| 后端 | FastAPI + SQLAlchemy 2.0 |
| 元数据 | SQLite |
| 向量库 | Chroma（1.0.x） |
| Embedding | BAAI/bge-small-zh-v1.5 |
| LLM | DeepSeek API（SSE 流式） |
| 前端 | React + Tailwind v4 + Vite |
| 客户端 | Electron |
| 外部数据源 | Bangumi API + 声明式自定义 |
| 测试 | pytest + pytest-cov（82%） |
| CI | GitHub Actions |
| 部署 | Docker + docker-compose |

---

## 相关文档

- [开发流程简报](开发流程简报.md)：开发过程、关键决策与踩坑记录
- `docs/decisions/`：9 份 ADR-lite 设计决策记录

## 声明

本项目的 RAG 核心逻辑（切分/检索/prompt 拼接）为手写实现，未使用 LangChain 等封装框架，目的是保持实现透明、可解释、可逐层讲解。
