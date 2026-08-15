# Tsumugi（紬）— 个人知识图书馆

一个**本地优先**的个人知识管理系统：收藏你喜欢的作品，记录你与这些作品之间发生过的经历，并让 Ask（Personal RAG）在之后把这段经历回想起来。

> 「紬（tsumugi）」意为手工织出的绸缎——把零散的资料与经历，织成属于你自己的知识体系。

这不是一个普通的作品管理器。普通的作品库回答的是「我看过什么」；Tsumugi 想逐步回答的是「我与这部作品发生过什么」。

---

## 核心能力

### 作品库 Library

- **作品条目**：统一模型收纳本地笔记与外部来源（Bangumi、萌娘百科、VNDB 等）收藏入库的作品
- **三种浏览方式**：网格 / 实体书架 / 分组列表
- **收藏关系**：收藏 / 追番状态 / 评分 / 喜欢标记，均与作品本体分开记录
- **导入**：Bangumi OAuth 批量导入你的收藏；单条外部结果一键收藏入库
- **数据备份**：导出 / 导入 JSON 备份（含笔记、书评、条目元数据、数据源配置，不含明文密钥）

### 作品详情 Work Detail

- **作品档案**：作品信息、简介、角色
- **我与它**：当前状态、态度（喜欢）、评分、书评入口
- **我的记忆**：内联「记录此刻」composer + 该作品的记忆时间轴
- **相遇纪事**：自动记录你与作品的收藏 / 评分 / 状态变化事件
- **往年今日 / 年度总结**：把回忆以时间线索带回来

### Memory（记忆）

Tsumugi 的记忆是**独立的容器**，收纳「值得被记住的时刻」：

- **直接记忆**：在作品详情「我的记忆」里写一句此刻的感想（`记录这一刻`）
- **情绪**：可选 emotion（怀念 / 感动 / 开心 / 难过 / 平静 …）
- **里程碑**：`完成了` / `重新打开` 会生成里程碑记忆
- **时间**：每条记忆带 `occurred_at`
- **向量化**：记忆正文切分后进入向量库（`source_type=memory`），参与个人语义检索

请区分四类内容：

| 类型 | 含义 |
| --- | --- |
| Memory | 你主动写下的直接记忆（含情绪 / 里程碑 / 时间） |
| Review | 你写的书评 / 读后感 |
| Note | 本地笔记 |
| External reference | 从外部数据源下载的百科资料 |

不要把自动导入的收藏/书评描述成你亲手写下的记忆——Tsumugi 始终区分「你写的」与「资料里的」。

### Ask / Personal RAG（检索台）

Ask 把你的个人记录（Memory / Review / Note）与外部资料结合起来回答：

- **我的检索**：作品 / 书评 / 记忆的结构化检索
- **外部检索**：已启用 Connector 的联合检索（Bangumi / Moegirl / VNDB）
- **综合回答**：基于检索结果 + LLM（DeepSeek）流式生成，回答区分「你的记录中……」与「资料显示……」

检索侧使用一组**个人语境信号**：

- **personal source weighting**：个人记录权重高于外部百科（避免资料抢占个人问题）
- **temporal**：`occurred_at` 参与「去年 / 最近 / 今年」等时间相关检索
- **emotion**：`emotion` 参与「印象深刻 / 怀念 / 感动」等情绪相关检索
- **milestone**：里程碑记忆参与「第一次 / 入坑 / 纪念」等检索
- **source-aware cap**：个人问题允许同一作品的不同个人来源（记忆 + 书评）同时进入上下文
- **provenance**：Ask 来源行展示个人记忆的时间 / 情绪 / 里程碑信息

需要如实说明的是：**这些信号用于检索排序，并不保证模型一定能回答任何个人问题**。

---

## Memory → Ask 数据链路

```
作品
 ↓
Memory / Review / Note / External
 ↓
metadata（occurred_at / emotion / milestone）
 ↓
vector（记忆正文向量化）
 ↓
semantic retrieval（个人记录权重优先）
 ↓
temporal / emotion / milestone signals
 ↓
metadata rerank
 ↓
source-aware cap
 ↓
provenance
 ↓
Ask（综合回答）
```

- `occurred_at` 用于「去年 / 最近」等时间相关检索
- `emotion` 用于「印象深刻 / 怀念 / 感动」等情绪相关检索
- `milestone` 用于「第一次 / 入坑 / 纪念」等里程碑相关检索
- `provenance` 让 Ask 来源展示这条个人记忆的时间 / 情绪 / 里程碑
- **历史向量兼容**：旧向量缺少新 metadata 时仍可正常检索；新写入的记忆会自动携带新 metadata

---

## 为什么 Memory 有价值

普通作品库记录的是关系事实「我看过《X》」，而 Memory 记录的是个人体验「这部作品让我很怀念。」带时间、情绪或里程碑的这类信息，会成为 Ask 回想个人经历时的检索信号——当你问「哪些作品让我印象深刻」「去年我留下了什么记录」时，检索能优先召回对应的记忆片段，而不是只靠语义偶然命中。

---

## Ask 示例

| 提问 | 使用的检索信号 |
| --- | --- |
| 「最近我留下了哪些记录？」 | temporal（occurred_at）|
| 「哪些作品让我印象深刻？」 | emotion intent + emotion metadata |
| 「我的入坑作品有哪些？」 | milestone intent + milestone metadata |
| 「我以前记录过哪些让我怀念的作品？」 | temporal + emotion |
| 「根据我的记录推荐几部作品？」 | recommendation（跨作品广度）+ personal source |

以上示例描述的是**检索机制**，不代表在任意数据上都会返回固定结果——实际结果取决于你积累了多少个人记录。

---

## Retrieval 设计

Ask 检索遵循以下流程（示例仅为机制说明，不代表固定结果）：

1. **semantic candidate**：向量相似度召回候选
2. **source strategy**：个人记录优先（memory / review / note），外部资料作补充
3. **metadata rerank**：在语义分数上叠加有限的 metadata 信号
4. **content dedup**：内容去重
5. **source-aware per-item cap**：按来源实体控制同一作品进入上下文的深度
6. **top-k**：最终截取

设计原则：

- **语义相关性仍是主导因素**，metadata signal 是有限的辅助信号
- external source 不获得 personal metadata boost
- unknown / invalid metadata 不会导致旧数据失效
- recommendation 保持跨作品广度
- personal / temporal 场景允许同一作品的不同个人来源实体共同出现

---

## Provenance

Ask 来源现在可以显示个人记忆的 `occurred_at` / `emotion` / `milestone`：

- 仅 Memory 来源使用这些字段
- Review / Note / External 不虚构这些 provenance
- 字段不存在时不会强行显示

---

## Experience Loop（如何积累记忆）

Tsumugi 在界面中提供了一条自然的记录路径，以及一些安静的引导：

```
作品详情
 → 我的记忆
 → 记录这一刻
 → 选择情绪 / 附图
 → 完成 / 重新打开
 → 时间轴 / Ask 回想
```

- 零记录作品的空态提示
- 收藏成功后的记录引导
- 标记「看完」后的就近记录提示
- composer 内对「情绪 / 里程碑」价值的简短说明

（这些是产品体验设计；目前没有真实用户增长数据来证明其留存效果。）

---

## 技术栈

| 模块 | 选型 |
| --- | --- |
| 后端 | FastAPI + SQLAlchemy 2 + Pydantic 2 |
| 元数据 | SQLite |
| 向量库 | Chroma（1.0.x）|
| Embedding | `BAAI/bge-small-zh-v1.5`（sentence-transformers）|
| LLM | DeepSeek API（OpenAI 兼容，SSE 流式）|
| 前端 | React 18 + Vite 6 + Tailwind CSS 4 |
| 客户端 | Electron（自动管理后端）|
| 外部数据源 | Bangumi / 萌娘百科 / VNDB Connector |
| 测试 | pytest（后端）+ Vitest（前端）|
| CI | GitHub Actions（后端 pytest + 覆盖率门槛 70%）|

---

## 项目结构

```text
Tsumugi/
├── app/
│   ├── main.py               # FastAPI 入口
│   ├── config.py             # 配置（pydantic-settings）
│   ├── database.py           # SQLAlchemy 引擎/会话/轻量迁移
│   ├── models.py             # Item / Chunk / Tag / Memory / Review / Collection / Character
│   ├── schemas.py            # Pydantic schema
│   ├── embeddings.py         # embedding 模型懒加载单例
│   ├── vectorstore.py        # Chroma 封装
│   ├── ingest.py             # 切分 + 入库 + 去重 + 删除
│   ├── retrieval.py          # 向量检索 + 来源权重 + metadata rerank + cap
│   ├── memories.py           # Memory 核心（记录/里程碑/向量化）
│   ├── rag.py                # prompt 拼接 + LLM 流式
│   ├── characters.py         # 角色实体化
│   ├── connectors/           # Connector 插件层（bangumi / moegirl / vndb）
│   └── api/routes.py         # API 路由
├── frontend/
│   ├── src/
│   │   ├── components/       # DesktopView / Bookshelf / ItemDetailPanel / Ask / 各房间
│   │   ├── api.js / toast.js / bookshelf.js / ...
│   │   └── electron/         # Electron 客户端
│   └── index.html / vite.config.js
├── tests/                    # pytest
├── requirements.txt
├── README.md
├── .env.example
└── start.bat                 # 一键启动
```

---

## 本地运行

### 环境要求

- Python 3.12（本项目在 Windows + Python 3.12 上开发验证）
- Node.js 20+
- npm

### 1. 配置环境变量

```bash
copy .env.example .env        # Windows
cp .env.example .env          # Linux / macOS
```

编辑 `.env` 填入真实值。至少需要 DeepSeek API Key 才能使用 Ask 的综合回答（AI 部分为可选扩展，核心库功能不依赖它）。

### 2. 安装依赖

```bash
# 后端
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / macOS
pip install -r requirements.txt

# 前端
cd frontend
npm install
```

> 首次使用 Ask 会触发 embedding 模型下载（`BAAI/bge-small-zh-v1.5`，可通过 `HF_ENDPOINT` 配置镜像）。

### 3. 运行

**方式一：一键启动（推荐）**

```bash
start.bat          # Web 模式：后端(8001) + Vite(5173) + 打开浏览器
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

**Electron 打包**（可选）

```bash
cd frontend && npm run dist   # electron-builder 生成 Windows 安装包
```

### 4. 使用

1. **导入**：在 Ask 检索外部作品并「收藏入库」，或连接 Bangumi 批量导入
2. **记录**：打开作品详情 → 「我的记忆」→ 写一句此刻的感想，可选情绪 / 附图
3. **回想**：在 Ask 提问，例如「哪些作品让我印象深刻」「最近我留下了哪些记录」
4. **浏览**：书库网格 / 实体书架 / 分组列表；人物档案、声优图谱、记忆回廊、时光轴

---

## 环境变量

以 `.env.example` 为准，这里说明用途（**不要把你的真实 Key 提交进仓库**；其余变量有默认值，按需调整）：

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 是（仅 Ask）| DeepSeek 平台 API Key |
| `DEEPSEEK_API_BASE` | 否 | LLM 接口地址（默认 `https://api.deepseek.com/v1`）|
| `DEEPSEEK_MODEL` | 否 | 模型名（默认 `deepseek-chat`）|
| `HF_ENDPOINT` | 否 | HuggingFace 镜像端点（默认 `https://hf-mirror.com`）|
| `TSUMUGI_PORT` | 否 | 后端端口（默认 8001）|
| `CHROMA_PERSIST_DIRECTORY` | 否 | Chroma 持久化目录 |
| `TOP_K` / `MAX_CHUNKS_PER_ITEM` | 否 | 检索参数（去重 / 深度）|
| `MAX_CONTEXT_LENGTH` | 否 | 参考资料上下文预算 |
| `UPLOAD_DIR` / `THUMBNAILS_DIR` | 否 | 上传 / 缩略图目录 |

---

## 测试

```bash
# 后端
.venv\Scripts\python.exe -m pytest -q      # 覆盖率门槛 70%

# 前端
cd frontend && npm test                    # Vitest
cd frontend && npm run build
```

> 最近一次验证基线：后端 pytest **483 passed**、前端 Vitest **299 passed**、`npm run build` 通过（该数字为上一次完整验证的结果，非每次提交都重新跑）。

---

## 当前状态与限制（诚实说明）

- **Memory 数据覆盖取决于你**：系统支持 `occurred_at` / `emotion` / `milestone`，但真实数据量取决于你主动记录；「代码支持」不等于「数据已经充分」。
- **历史向量兼容**：历史向量可能缺少新 metadata——不要求重建历史向量；缺失 metadata 时仍可正常检索；新写入的记忆会携带新的 metadata。
- **Retrieval 限制**：metadata signal 是辅助排序信号；个人召回质量依赖你实际积累的 Memory；不能保证所有「为什么 / 什么时候 / 我喜欢什么」类问题都有对应个人记录；也不要把统一向量检索理解成完整的个人知识库。
- **AI 能力边界**：Ask 只依据检索到的资料作答，不保证对任意问题给出正确或个性化的回答。

---

## 安全 / 隐私

- `.env` 不应提交；仓库只包含 `.env.example` 占位模板。
- 本地数据库、Chroma 向量库、上传与缩略图目录属于本地运行数据，均在 `.gitignore` 中排除。
- 你的个人 Memory 属于个人数据，请谨慎处理；本项目不做「绝对安全 / 完全隐私」的承诺。

---

## License

当前仓库**未声明许可证**。如需在公开场景使用或分发，请先与我们联系确认授权方式。
