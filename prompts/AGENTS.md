# AGENTS.md — Tsumugi（紬）个人知识图书馆系统

## 项目定位

**Tsumugi 是一个开源、可自定义的二次元私人图书馆：收藏作品，也收藏与作品相遇时留下的自己。**

项目定位与架构基准以 `docs/product-brief-v1.1.md` 为准（v1.1 由 v1.0 合并现状校验
附录校准而成，修订明细见该文末【v1.1 修订记录】）。核心原则：

- **Work 是核心馆藏对象，Book / Shelf 是 UI 隐喻**（数据模型不叫"书"，管理对象是
  Anime/Manga/Galgame/VN/Game/Novel 等作品）
- **世界轴 + 我的轴**：世界轴描述作品本身（角色 / 制作 / 系列 / 外部资料），我的轴
  描述"作品在我这里留下了什么"（收藏 / 状态 / 评分 / Review / Memory / Timeline）。
  Tsumugi 的核心价值是 **"作品 × 我的经历"**，不是"查询作品"
- **Memory 是独立容器**：收纳"图书馆里发生过的、值得被记住的时刻"，Review 只是其中
  一种来源，Memory 不是 Review 的视图；Experience 是语义聚合概念不建表；Timeline 是
  查看方式，不是独立数据实体
- **AI / RAG 是可选扩展，不是 Core**：Core 无 AI 也完整（默认无需 API Key / Ollama /
  Embedding / 向量库配置）；AI 是"图书馆的检索与记忆能力"，不得创造不存在的用户记忆，
  回答必须区分"我的资料"与"外部资料"来源
- **UI 是图书馆的空间隐喻**：检索台 / 书库 / 人物档案馆 / 关系厅 / 记忆回廊 / 管理室，
  不是 Dashboard / Card / Table / Chat / Status Badge 的堆叠；UI 北极星见
  `prompts/AGENT_UI_v2.1.md`（长期愿景，执行范围以当前 Phase 排期为准）
- 核心检索/prompt 逻辑仍不依赖 LangChain 等封装框架手写实现，理由不是"练手"，
  而是保持实现透明、可解释、可讲清楚每一步——即便开发方式已调整为 Agent 主导（见下）
- 面向目标仍然包括：开源作品集展示 + 能讲清楚 RAG 原理与系统设计的项目

**基准文档与开发提示词（2026-08-09 起）**：

- 产品/架构基准：`docs/product-brief-v1.1.md`（原始讨论稿保留在
  `E:\program\MyProject\项目简报\Tsumugi\`）
- 开发提示词：以 `prompts/` 文件夹为准（00 基准校准 → 01 PhaseA Memory → 02 PhaseB
  作品记忆时间轴 → 03 PhaseC 记忆回廊…），后续开发提示词均引用此基准
- 开发阶段规划：以 product-brief-v1.1.md 第二十三节 **Phase A → G** 为准

---

## 协作模式（相对旧版的重大变更）

**旧方案**：核心逻辑（`ingest.py`/`retrieval.py`/`rag.py`）由用户手写，
AI只提供函数签名+docstring+TODO，遇到问题优先给思路不给代码。

**新方案**：**取消该限制**。全部代码——包括核心检索/prompt拼接逻辑、
Connector插件、前端UI——由Agent自主设计并实现。用户角色是产品决策者与
验收者，不需要亲自写代码。

保留下来、依然重要的原则：

1. **不依赖LangChain等RAG封装框架**实现核心检索/prompt逻辑——不是因为
   "要练手"，而是为了让实现保持透明、可拆解、可在面试中逐层讲清楚。
2. **每个非平凡设计决策需要留痕**：Agent在完成一个阶段/一次较大改动后，
   除了代码本身，还要输出一份简短的"变更说明 + 关键决策记录"
   （为什么这样设计、放弃了哪些方案、权衡是什么），供用户审查，也是
   用户日后能对着项目讲清楚原理的基础。建议存放在 `docs/decisions/`
   下，一个决策一个短文件（ADR-lite风格），不需要长篇大论。
3. **阶段化交付、随时可暂停**：每个Phase是一个独立可验收的增量，互不
   阻塞，用户可以随时插入审查/调整方向，也可以让Agent继续往下推进而
   不等待逐行确认。
4. **测试不可省略**：pytest覆盖核心逻辑（切分策略、检索排序、connector
   normalize逻辑）与API接口，CI跑测试——这部分是简历/作品集的加分项，
   不因为"AI写的"就降低标准。
5. **允许先行反馈优化意见**：执行项目过程中，如发现可优化之处或更好的
   项目方向/实现方案，Agent应主动、先行向用户反馈（附理由与影响范围），
   由用户决策后再实施；与当前任务强相关的小优化可直接实施，但需在变更
   记录中说明原因与取舍。
6. **硬性规则：涉及含中文内容的文件，一律用编辑工具（str_replace /
   create_file）操作，禁止用 Shell 重写**（PowerShell 的
   `Set-Content`/`Out-File`/`Add-Content` 等会以非 UTF-8 编码重写文件，
   导致中文乱码损坏；历史教训见简报"编码事故"条目）。
7. **Electron 冒烟测试必须验证真实数据请求（不只是 health 检查）**：任何
   涉及 Electron 相关改动（preload / 打包 / 后端端口 / 路径拼接）后，冒烟
   测试除了 `GET /health` 外，**必须额外实际发一次数据请求**（如
   `GET /api/items` 或 `GET /api/connectors`），断言返回非 404 且含预期
   数据。历史教训：`preload.cjs` 的 `apiBase` 缺 `/api` 前缀导致 Electron
   客户端**所有 API 请求 404**，但只测 health 的冒烟测试全部通过，问题被
   "冒烟测试通过"掩盖（详见简报对应条目）。默认动作：改完 Electron 相关
   代码后在真实 Electron（`--remote-debugging-port` 驱动）或至少在后端进程
   上验证一次真实数据请求。

---

## 开发简报（永久约定，重写/修改本文件时不得删除本节）

本项目有**两类简报**，都是长期习惯，任何情况下都不得中断：

1. **逐条变更记录**：仓库根目录 `开发流程简报.md`。**每次修改文件（代码或文档），
   都必须在其中追加一条变更记录**，写明改了什么、关键点/坑位，方便回溯与复习
   （文件头有详细约定）。这是本项目最核心的协作习惯。
2. **产品方向/讨论简报**：存放在 `E:\program\MyProject\项目简报\Tsumugi\`，
   例如《Tsumugi 最终项目开发简报 v1.0》《Tsumugi 2.0 讨论结论简报 v0.2》
   《v1.0 现状校验附录》等。这类文档定义产品定位与架构基准（如"世界轴/我的轴"、
   Memory 独立容器、AI 为可选扩展、记忆回廊等），后续开发提示词以它们为基准，
   与逐条变更记录是两类东西，都要保留。

书写要求（与协作模式规则 6 一致）：含中文内容的简报/文档一律用编辑工具
（read / edit / write）操作，禁止用 Shell（`Set-Content`/`Out-File`/
`Add-Content` 等）重写，避免编码乱码。

**红线**：本节的"开发简报"书写习惯与提示词是用户明确要求永久保留的约定——
今后无论何时重写、精简或更新 AGENTS.md，都必须原样保留本节，不得删除或弱化。

---

## 系统架构总览

```
┌─────────────────────────────────────────────┐
│  表现层：React + Tailwind，主题/布局可自定义    │
└───────────────┬─────────────────────────────┘
                 │ REST/SSE
┌───────────────▼─────────────────────────────┐
│  API层：FastAPI 路由                          │
├───────────────┬─────────────────────────────┤
│  检索编排层     │ 联合检索：本地向量检索 + 已启用   │
│  (retrieval)   │ Connector的实时/缓存检索结果合并  │
├───────────────┼─────────────────────────────┤
│  RAG核心层      │ prompt拼接 + DeepSeek API      │
│  (rag.py)      │ （手写，不用LangChain）         │
├───────────────┼─────────────────────────────┤
│  Connector插件层 │ 统一接口：search/get_detail/  │
│                │ normalize，各数据源独立实现      │
├───────────────┼─────────────────────────────┤
│  数据层         │ SQLite(元数据) + Chroma(向量)   │
└─────────────────────────────────────────────┘
```

---

## 数据模型（在原模型基础上扩展）

```
Item（资料条目，统一模型，本地与外部数据源共用）
├── id
├── title
├── type: "note" | "image" | "external_ref"
├── content: markdown文本（note类型，含从外部摘要转存的情况）
├── file_path: 本地图片路径（image类型）
├── image_url: 外部数据源封面图（与file_path区分：一个是本地存储，
│              一个是外部链接/缓存后的本地缩略图路径）
├── source: "local" | "bangumi" | "vndb" | ...（对应已注册Connector）
├── external_id: 在对应数据源中的原始ID（用于去重、二次拉取详情）
├── raw_metadata: JSON，存放外部API原始返回（预留字段扩展空间，
│                 避免以后每加一个字段都要改表）
├── synced_at: 外部数据最后同步时间
├── created_at / updated_at
└── tags: 多对多关联 Tag

Chunk（切分块，note类型及"收藏入库"的外部摘要文本产生）
├── id / item_id / content / chunk_index / embedding_ref

Tag
├── id / name

Source（新增：已注册的数据源/插件清单）
├── id
├── name: 如 "bangumi"
├── type: "local" | "connector"
├── enabled: 是否启用
├── config_ref: 指向该connector的配置（含加密后的API Key引用，
│               不落库明文）
└── rate_limit_config: 该数据源的限流参数
```

设计要点：外部数据不直接大量落库，`raw_metadata`兜底存原始JSON，正式
字段只提炼真正会被检索/展示用到的部分，避免过早为不确定的未来字段
设计表结构。

---

## Connector 插件架构（本次重构的核心新增部分）

### 统一接口

```python
class Connector(Protocol):
    name: str                     # 唯一标识，如 "bangumi"
    manifest: ConnectorManifest   # 见下

    def search(self, query: str, **filters) -> list[SearchResult]:
        """调用外部API搜索，返回未落库的轻量结果（标题+封面+摘要），
        用于联合搜索结果列表展示。"""

    def get_detail(self, external_id: str) -> ItemDetail:
        """拉取完整详情（角色、关联条目等），用户点开某条结果时调用。"""

    def normalize(self, raw: dict) -> Item:
        """把外部API原始返回，转换成本地统一Item结构，
        用于"收藏入库"时写入数据库。"""
```

### Manifest（每个Connector自描述）

```json
{
  "name": "bangumi",
  "display_name": "Bangumi 番组计划",
  "version": "0.1.0",
  "auth_type": "api_key | oauth | none",
  "base_url": "https://api.bgm.tv",
  "rate_limit": { "requests_per_minute": 60 },
  "capabilities": ["search", "get_detail"]
}
```

manifest让"新增一个数据源"变成"写一个实现+一份manifest+注册"，而不是
改动核心检索编排代码。

### 配套能力

- **密钥管理**：每个Connector的API Key单独加密存储（不写入代码/不落库
  明文），通过`config_ref`引用；用户在设置页填写，不出现在Git历史里。
- **限流与缓存**：统一的请求缓存层（同一query短时间内不重复打外部API），
  尊重各数据源的速率限制，避免被封key。
- **图片处理策略**：外部封面图默认展示原始链接；用户执行"收藏入库"时，
  才缓存一份本地缩略图（避免大规模热链导致的失效/带宽问题，也避免
  未经用户明确操作就批量搬运版权图片）。
- **收藏入库（Save to Library）**：外部搜索结果可以一键转为本地Item——
  仅存摘要/简介文本进入向量库参与RAG检索，不做全文抓取存储，兼顾
  实用性与版权边界。
- **插件安全边界**：如果未来支持"用户自己上传Connector代码"（Phase 4
  的自定义API源），建议走**声明式配置**（HTTP端点+字段映射规则）而不是
  执行任意Python代码；确需支持代码级插件时，要有沙箱/权限清单机制，
  这是个人项目里最容易被忽略但线上风险最高的一环。

---

## 第一个Connector实现：Bangumi

作为Connector抽象的验证案例，接入 [Bangumi API](https://bangumi.github.io/api/)：

- **search**：按关键词搜索动画/游戏/书籍条目，返回标题、封面图、简介、
  评分、标签
- **get_detail**：拉取角色列表、关联条目、更完整的简介
- 验证通过后，同一套Connector接口可平移接入VNDB、豆瓣、MAL等，
  Phase 3完成即证明"插件化架构成立"，Phase 4是把它泛化成用户可自助
  接入的能力。

---

## UI自定义能力

- **主题系统**：基于CSS变量的可切换主题，可以做和galgame/日系美术
  相关的主题（例如"书斋"风、四季限定主题），不绑死单一视觉风格。
- **布局自定义**：仪表盘式，用户可增删/排列面板（最近检索、收藏、
  标签云、各数据源快捷入口）。
- **联合搜索结果的来源角标**：本地 / Bangumi / 其他数据源用视觉上
  可区分的标签标出，避免用户混淆"我自己的资料"和"外部检索结果"。

---

## 技术栈（更新）

| 模块             | 选型                                | 备注                                       |
| ---------------- | ------------------------------------ | ------------------------------------------- |
| 后端             | FastAPI（不用LangChain）             | 手写检索+prompt拼接，便于讲清楚原理          |
| 数据库（元数据） | SQLite（Phase 1）→ 可迁移PostgreSQL  | 存Item/Tag/Chunk/Source元信息               |
| 向量库           | Chroma                               | 存文本chunk的embedding                      |
| Embedding模型    | BAAI/bge-small-zh-v1.5               | 中文效果好，前项目已验证可用                 |
| LLM API          | DeepSeek API                         | 复用已有API key                             |
| 外部数据源       | Bangumi API（首个）→ VNDB/豆瓣/MAL   | 统一Connector接口接入                        |
| 缓存层           | SQLite简单缓存表（够用即可，非必须Redis）| 外部API请求结果缓存，控制调用频率        |
| 密钥管理         | 环境变量/加密配置文件                 | 不落库明文，不进Git历史                     |
| 前端             | React + Tailwind                     | 支持流式输出(SSE/WebSocket)，主题/布局可配置 |
| 测试             | pytest                               | 覆盖检索逻辑、connector normalize、API接口   |
| 部署             | Docker + docker-compose              | 比PyInstaller更贴近工程规范                  |
| CI               | GitHub Actions                       | 跑pytest，简历加分项                         |

---

## 开发阶段规划（更新）

| 阶段        | 内容                                                         | 状态      |
| ----------- | -------------------------------------------------------------- | --------- |
| **Phase 1** | 本地RAG核心：文档导入/切分/embedding/检索/prompt拼接           | 🔧 进行中 |
| **Phase 2** | 标签系统 + 结构化筛选（数据库设计、SQL查询逻辑）                | 待开始    |
| **Phase 3** | Connector插件框架 + Bangumi作为首个实现，验证联合检索/收藏入库  | 待开始    |
| **Phase 4** | 插件架构泛化：用户可自助接入新数据源（声明式配置优先）          | 待开始    |
| **Phase 5** | UI自定义（主题/布局）+ Docker + CI 打磨                        | 待开始    |

每个Phase完成即是一个可展示、可讲清楚原理的增量，Phase 1完成后系统已
经是一个完整可用的本地RAG项目，后续阶段不阻塞前面的可用性。

---

## Phase 1 详细范围（沿用原规划）

**支持内容类型**：Markdown/纯文本笔记 + 图片（附件形式存储，不做多模态
语义检索，列为未来扩展点，避免MVP阶段范围失控）

**核心文件与要点**（现由Agent实现，但设计思路仍需在决策记录中说明）：

- `ingest.py`：文档切分策略（按段落/固定长度/语义边界）、chunk_size/
  overlap取值及理由、图片入库方式（仅存路径+元数据，不切分）
- `retrieval.py`：向量检索与tag过滤组合（tags=None全库检索，tags不为空
  先SQL筛选item_ids再向量检索）、结果排序/去重逻辑
- `rag.py`：检索结果→prompt拼接模板与策略、超长上下文截断策略、
  DeepSeek API调用（含SSE流式响应）、异常处理（API失败/超时/embedding
  失败）

---

## 项目目录结构（更新）

```
Tsumugi/
├── app/
│   ├── main.py               # FastAPI入口
│   ├── config.py             # 配置管理（.env加载，含各connector密钥引用）
│   ├── database.py           # SQLAlchemy引擎/会话
│   ├── models.py             # ORM模型（Item/Chunk/Tag/Source）
│   ├── schemas.py            # Pydantic schema
│   ├── ingest.py             # 文档切分与入库
│   ├── retrieval.py          # 本地检索逻辑
│   ├── rag.py                # prompt拼接 + API调用
│   ├── connectors/
│   │   ├── base.py           # Connector Protocol定义
│   │   ├── registry.py       # Connector注册/发现机制
│   │   └── bangumi/
│   │       ├── manifest.json
│   │       └── connector.py  # search/get_detail/normalize实现
│   └── api/
│       └── routes.py         # API路由（本地检索 + 联合检索 + 收藏入库）
├── frontend/
│   ├── src/
│   │   ├── themes/           # 可切换主题（CSS变量）
│   │   └── components/dashboard/  # 可自定义布局的面板组件
├── tests/
│   ├── conftest.py
│   ├── test_retrieval.py
│   └── test_connectors/
│       └── test_bangumi.py   # 用mock响应测试normalize逻辑
├── docs/
│   └── decisions/            # ADR-lite决策记录，每阶段产出
├── data/
│   └── uploads/
├── requirements.txt
├── .env.example
└── AGENTS.md
```

---

## 未来扩展点（不在当前阶段实现，先预留设计空间）

- 图片语义检索（CLIP等多模态embedding）
- 向量库从Chroma迁移至Qdrant/pgvector（生产级）
- 更多Connector：VNDB、豆瓣、MyAnimeList
- 代码级自定义插件的沙箱执行环境（如果Phase 4决定支持"用户上传代码"
  而非纯声明式配置）
- MMR多样性重排序（`calculate_diversity_score`），原计划Phase 1实现，
  现推迟到Phase 2及以后
- 本地库数据导出/备份（考虑到这是"个人图书馆"，长期看用户会积累不少
  收藏数据，导出能力值得较早规划，即使晚实现）
