# PROJECT_AUDIT_REPORT.md — Tsumugi 项目审查报告

> 阶段：第一阶段 · 项目审查（Existing Project Audit）
> 日期：2026-08-09/10
> 性质：**只读审查，本轮未修改任何代码**
> 回档节点：git tag `pre-refactor-2026-08-10`

---

## 一、项目现状

### 1.1 项目结构

```
Tsumugi/
├── app/                    # FastAPI 后端
│   ├── main.py / config.py / database.py / models.py / schemas.py
│   ├── ingest.py / retrieval.py / rag.py / embeddings.py / vectorstore.py
│   ├── reviews.py / memories.py / external_refs.py / images.py / stats.py
│   ├── providers.py / provider_store.py / plugins.py / backup.py
│   ├── bangumi_oauth.py / bangumi_import.py
│   ├── connectors/         # bangumi / moegirl / vndb + 声明式自定义源 + ssrf/base/registry/persistence
│   └── api/routes.py       # 全部 REST 路由
├── frontend/               # React + Vite + Tailwind v4 + Electron 壳
│   ├── src/api.js          # API 客户端
│   ├── src/components/     # 25 个组件（DesktopView 三栏壳 + 各视图/弹层）
│   ├── src/mascot.js / markdown.js / commands.js / themes.js / ambient.js / bookshelf.js / toast.js
│   └── electron/           # main.cjs（自动管理后端）
├── tests/                  # pytest（26 文件）
├── frontend/src/test/      # vitest（23 文件）
├── docs/decisions/         # 43 份 ADR-lite（0001–0044）
├── data/                   # chroma / thumbnails / uploads（gitignored）
├── prompts/                # 开发提示词 + 设计文档（gitignored，私有）
└── 项目简报/                # 讨论简报（v0.1/v0.2/v1.0/校验附录）——仓库外
```

### 1.2 技术栈

| 层 | 选型 | 备注 |
| --- | --- | --- |
| 后端 | FastAPI + SQLAlchemy 2 + SQLite | 手写检索/prompt，不依赖 LangChain |
| 向量 | Chroma（Rust core）+ bge-small-zh-v1.5（sentence-transformers） | |
| LLM | Provider 可插拔：DeepSeek / OpenAI 兼容 / Ollama | 无 AI 模式可用 |
| 前端 | React 18 + Vite + Tailwind v4 + Electron | Web/客户端共用 |
| 测试 | pytest 410（覆盖率 86.91%）+ vitest 198 + build 通过 | |

### 1.3 功能状态

**已完成并实测（本轮会话 + 历史）：**
- 本地 RAG（note/review/external_reference 三来源，检索加权 + 来源标注）
- 联合检索（bangumi/moegirl/vndb/声明式自定义源 + 代理 + SSRF + 限流 + 缓存）
- 外部资料本地化下载参与检索（ADR 0025/0026）
- 书评系统（多篇、评分聚合、spoiler 过滤、Markdown 编辑器/工作室、字号）
- **Memory Core（Phase A）**：Memory 表 + Review 生命周期自动同步 + 回填
- **作品时间轴（Phase B）**：详情页"外部世界/我的记录"双栏 + 正序时间轴 + 只读弹层
- **记忆回廊（Phase C）**：年组编年列表 + 年份/作品筛选
- **往年今日（Phase E）**：猫娘唤起 + 最高优先级 + 只读弹层
- 角色墙 / 声优关系图谱 / 年度热力图 / 封面动态取色 / 神殿首页 + 看守猫娘台词系统
- 备份/导出/导入（JSON 幂等合并，真实闭环）/ 代码级插件 / 命令面板 / 批量操作
- 四套收敛主题 + 有约束自定义

**已知未完成：**
- Work 模型泛化（anime/manga/game… 类型）——Phase F
- Memory 素材扩展（轻量文字/截图/收藏时刻/里程碑）——Phase D
- Collection 独立实体化；Media 附件实体；Character/Series/Creator 实体化
- 统一"个人检索台"（Memory/Review 文本搜索）——Search Desk
- Personal RAG（Memory 进检索）——Phase G
- Electron 独立打包 embedding 可用性（ADR 0012 已知阻塞）

### 1.4 数据模型（现状）

数据库表：`items, chunks, tags, item_tags, reviews, memories, sources, llm_providers`

- **Item** = 统一"资料条目"（type: note/image/external_ref），外部字段靠 `raw_metadata` JSON
- **Memory**（Phase A）：独立容器，source_type=review（预留 text/image/collection/milestone）
- **Review**：正式书评（评分/状态/多篇/source 去重）
- **Character/Series/Creator**：**无表**——内嵌 raw_metadata，查询时聚合扫描
- **Collection/Media**：**无表**——收藏状态散落在 Review.status；图片走 Item(type=image)/thumbnails
- **Timeline**：视图逻辑（Memory.occurred_at 排序），非表——与 v1.1 一致

### 1.5 UI 结构

- 三栏壳：左导航栏（检索台/书库/人物档案馆/关系厅/记忆回廊/管理室）+ 侧栏 + 工作区
- 视图：神殿首页（Shrine）、网格/书架/状态分组列表（主从）、角色墙、声优图谱、年度总结、记忆回廊、分析、设置
- 弹层：只读书评、Review Studio、详情、安利卡、标签编辑等

---

## 二、当前优势

1. **可用的完整底座**：410 pytest + 198 vitest + build 全绿，功能覆盖广，不是空壳。
2. **情感核心已落地**：Memory → 作品时间轴 → 记忆回廊 → 往年今日 这条"记忆"链路真实可用
   （Phase A/B/C/E 全部实测通过），直接兑现"作品 × 我的经历 × 记忆"定位。
3. **AI 已正确"Extension 化"**：Provider 可插拔、无 AI 模式完整可用、检索来源区分
   （我的书评/我的笔记/百科资料）。
4. **工程纪律好**：43 份 ADR 留痕、简报逐条变更记录、双端测试、实测闭环（headless
   Chrome CDP 截图验证）。
5. **主题与视觉收敛**：四套克制主题 + 共享 token（ADR 0020），神殿首页/猫娘/氛围色
   已接近"图书馆"而非"工具"。
6. **数据可携带**：备份/导出/导入幂等闭环，本地优先。

---

## 三、存在问题（按影响排序）

1. **Item 模型是"通用条目"，不是"作品（Work）"**
   - type 混用内容类型（note/image）与作品类型；没有 anime/manga/game… 维度；
   - alternative_title / release_date / creator / series / genre 等世界轴字段缺失或
     深埋在 `raw_metadata` JSON——**不可查询、难演进**。
2. **Character/Series/Creator 无实体**
   - 角色墙/声优图谱每次聚合扫描 raw_metadata（规模上来会慢）；
   - 角色不能独立关联 Memory（v1.1/07 都要求"用户可能因为角色产生长期记忆"）。
3. **Collection 未独立**：收藏状态 = Review.status（Bangumi 导入产生的空内容 Review），
   "何时收藏/是否喜欢/收藏时刻 Memory"没有独立承载（Phase D 缺口）。
4. **Memory 素材类型单一**：只有 review；轻量文字、截图/插图（Media）、收藏时刻、
   里程碑都没有；Memory 无 media 引用、无 emotion 等语义字段。
5. **搜索未统一**：世界检索（联合搜索）与我的检索（RAG）是两套入口（v1.1 校验附录已
   标注）；Memory/Review 无文本搜索；Personal RAG 未做。
6. **UI 仍有"工具后台"残迹**：分析（Inspector）/年度热力图偏仪表盘；书架仍是"书脊
   列表"非真书架（ADR 0019，AGENT_UI v2.2 已标为有意推翻目标）；侧栏/分组列表较表格化。
7. **Electron 独立打包 embedding 不可用**（transformers `_LazyModule` 与 PyInstaller
   PYZ 冲突，ADR 0012 止损）。Docker 是当前主要分发路径。
8. **环境/杂物**：`.venv` 含 chromadb 传递依赖 `kubernetes`（75MB 死重，不参与打包）；
   历史简报有少量编码遗留（已随用随修）。
9. **提示词/设计文档已私有化**（`prompts/` gitignored）：新克隆不含 agent 指令与
   04-26 设计文档，需要单独保存/归档，避免丢失。

---

## 四、与 Tsumugi 目标架构的差距

| 目标实体（14/07 文档） | 现状 | 差距等级 |
| --- | --- | --- |
| Work（Type/系列/创作者/发行/别名） | Item 通用条目，raw_metadata JSON | **高** |
| Collection（状态/加入时间/喜欢） | Review.status 零散承载 | **高** |
| Memory（独立容器/多素材/媒体/情绪） | 有表但仅 review 来源、无 media | **高（部分已做）** |
| Character（独立实体/多作品/角色 Memory） | 无表，raw_metadata 内嵌 | **高** |
| Series / Creator | 无表，仅标题模糊匹配 related | 中 |
| Media（截图/插图/视频） | 无表，图片=Item 或缩略图文件 | 中 |
| Timeline Event | 用 Memory.occurred_at 视图实现（v1.1 认可） | 低 |
| Search Desk（作品/角色/Memory/Review） | 世界/我的两套入口，无 Memory 文本搜索 | **高** |
| Personal RAG（Memory 进检索） | Review/note/external 在 RAG，Memory 未进 | 中 |
| AI Provider（Ollama/API/无 AI） | **已完成**（providers.py） | ✅ |
| 数据可携带（导出/备份/迁移） | **已完成**（backup.py 闭环） | ✅ |
| Local First / 用户数据隔离 | **已完成**（本地库，个人数据不落外部） | ✅ |

---

## 五、重构优先级（渐进，不推倒重写）

依据 13 号执行计划"先 Core 后 Extension、先稳定数据再优化体验、先最小闭环"：

| 优先级 | 内容 | 对应 Phase | 说明 |
| --- | --- | --- | --- |
| P0 | 稳定现有工程 | — | 当前 410/198 全绿即为基线；tag `pre-refactor-2026-08-10` 兜底 |
| P1 | **Work 模型泛化** | F | 先出 `WORK_MODEL_DESIGN.md`；给 Item 加 type(作品维度)/别名/发行/creator/series，从 raw_metadata 提炼可查询列；**不推倒 Item，加列 + 迁移** |
| P2 | **Collection 独立** | D | Collection 实体（状态/加入时间/喜欢）+ 收藏时刻自动生成最轻 Memory |
| P3 | **Memory 扩展** | D | 轻量文字/截图 Media/里程碑；Media 附件实体；可选 emotion |
| P4 | **Character/Series 实体化** | — | 从 raw_metadata 提炼为表，角色墙/声优图谱改走表；角色可关联 Memory |
| P5 | **Library 体验** | — | 真书架（对 ADR 0019 有意推翻，需新 ADR）、首页"最近记忆/最近收藏"、去除工具感 |
| P6 | **Search Desk** | — | 统一个人检索：Memory/Review/作品文本搜索 + 现有联合检索合并入口 |
| P7 | **Personal RAG** | G | Memory/Review 进统一个人语义检索，保持我的/外部来源区分 |
| P8 | 工程收尾 | — | Electron 打包 embedding、venv 瘦身（移除 kubernetes）、文档归档 |

> 注意：P1/P2/P3/P4 是"数据层"改动，必须先出设计文档（14 号输出 DATABASE_SCHEMA_DESIGN.md）、
> 有完整迁移方案、实测迁移后再动，否则破坏现有 63 条真实数据与 Memory 完整性。

---

## 六、风险分析

1. **数据迁移风险（最高）**：Item→Work 泛化、Character/Series 实体化都要动现有 63 条
   真实条目 + 已回填的 58 条 Memory。缓解：先写迁移设计 + 备份验证 + 空库/样例库双测；
   保持幂等（复用 ensure_schema + 回填模式）。
2. **范围蔓延**：master 指令 + 26 份设计文档信息量大，容易"一次做太多"。缓解：坚持
   Core 优先、每次一个小版本、每次改动走"分析→方案→确认→实现→测试→总结"。
3. **与既有 ADR 冲突**：Work 泛化会推翻 ADR 0016（角色 raw_metadata 内嵌）、书架会推翻
   ADR 0019——执行时必须在新 ADR 里写明"有意推翻 + 理由 + 与旧决策整合"。
4. **Electron 打包**：embedding 问题涉及 transformers 与 PyInstaller 深层兼容，短期不
   阻塞 Web/本地开发；Docker 路径已验证。列为 P8 收尾，不因它阻塞 Core 演进。
5. **提示词私有化后的可恢复性**：prompts/ 已 gitignored，若误删无版本保护。建议定期
   归档一份到仓库外的备份目录。

---

## 七、后续开发建议

1. **立即执行**：以本报告 + 13 号执行计划为序，从 P1（Work 泛化）开始；先产出
   `WORK_MODEL_DESIGN.md`（07 输出要求）供人工确认，再动数据层。
2. **每个阶段交付固定四件套**：ADR 决策记录 + 开发流程简报条目 + 双端测试 + 真实数据
   实测（截图/CDP），延续既有纪律。
3. **每次大规模改动前**先打 tag/commit 检查点（本次已做 `pre-refactor-2026-08-10`）。
4. **设计文档归档**：把 prompts/ 04-26 文档在仓库外备份一份，防止私有化后丢失。
5. **继续维护"我的轴 > 世界轴"**：任何新 UI 先问"它是在增强作品×经历×记忆，还是只是
   加了个软件功能"（04 号三个问题）；工具感部分（分析/热力图）逐步收敛进"管理室"。

---

> 审查结论：Tsumugi 已具备"私人图书馆"的功能骨架与记忆情感核心（A/B/C/E 真实可用），
> 主要差距在**数据模型层**（Work/Collection/Character/Media 未实体化）与**个人检索**
> （Search Desk / Personal RAG）。按 Core 优先、数据先行、小版本渐进的原则推进重构。
> 等待人工确认后进入下一阶段。
