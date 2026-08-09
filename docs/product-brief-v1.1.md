# Tsumugi 最终项目开发简报
## Final Product & Architecture Brief v1.1

> **文档性质：最终方向简报 / 重构基准（校准版）**
>
> 本文由《Tsumugi 最终项目开发简报 v1.0》合并《v1.0 现状校验附录》的四处修正而成。
> **v1.1 相比 v1.0 仅做了四处修订**（Connector 现状、检索台架构图现状/目标标注、
> 真书架与 ADR 0019 的关系、插件沙箱表述），其余章节原样沿用。
> 修订明细见文末【v1.1 修订记录】。
>
> **用途：**作为后续产品、架构、UI、数据库与 Agent 开发提示词的共同基准，统一
> Tsumugi 的 Core 定位，防止后续开发重新滑向"普通二次元数据库 / AI Chat 工具"。
> 原始讨论稿仍保留在 `E:\program\MyProject\项目简报\Tsumugi\`（v1.0 / v0.2 / v0.1），
> 本文是经过事实核校、可直接被开发提示词引用的版本。
>
> **重要：**本文确定的是产品与架构方向，不等同于立即一次性完成所有功能。具体开发仍应
> 分批推进、逐步验收（Phase A → G，见二十三节）。

---

# 一、项目最终定位

> **Tsumugi 是一个开源、可自定义的二次元私人图书馆：收藏作品，也收藏与作品相遇时留下的自己。**

Tsumugi 管理的对象不是传统意义上的"书"，而是各种作品：

- Anime
- Manga / Comic
- Galgame
- Visual Novel
- Game
- Novel
- 其他 ACG / 二次元相关作品

"图书馆"是 Tsumugi 的**空间隐喻与交互语言**，而不是数据模型限制。

```text
Book ≠ Core Entity
Work = Core Entity
Book / Shelf / Archive = UI / Information Architecture Metaphor
```

---

# 二、项目定位的根本变化

Tsumugi 最初的方向是：

```text
二次元数据库
      ↓
本地 RAG
      ↓
AI 查询
```

这个方向本身没有错误，但容易把 Tsumugi 做成"一个更漂亮、更方便的二次元数据库"。

真正的差异化应该来自：

> **世界轴 + 我的轴**

## 2.1 世界轴

描述作品本身：

```text
Work
├── Character
├── Creator / Staff
├── Series
├── Genre / Tags
├── External Data
└── Related Works
```

回答：

> **"这个世界是什么？"**

## 2.2 我的轴

描述作品与用户之间发生过什么：

```text
Work
├── Collection
├── Status
├── Rating
├── Review
├── Memory
├── Media
└── Timeline
```

回答：

> **"这个作品在我这里留下了什么？"**

因此 Tsumugi 的真正核心不是"查询作品"，而是：

> **作品 × 我的经历。**

---

# 三、Experience：Core 的上层概念

`Experience` 不应该成为一张独立数据库表。

它是一个**语义聚合概念**：

> 某个 Work + 该 Work 下的 Review / Memory + 收藏状态 + 评分 + 其他相关记录。

```text
Experience ≠ Database Entity
Experience = Semantic Aggregate
```

这样可以避免把 Review、Memory、Timeline、Experience 错误地设计成多个互相竞争的实体。

---

# 四、Memory：Tsumugi 最重要的新 Core

## 4.1 Memory 的最终定义

> **Memory 是独立的容器，用于收纳"图书馆里发生过的、值得被记住的时刻"。**

Memory 不是 Review 的视图。

Review 只是 Memory 的一种重要来源。

```text
Memory
├── Review
├── Lightweight Memory（未来）
├── Screenshot / Image（未来）
├── 收藏时刻（未来）
└── Other Memory Sources（未来）
```

## 4.2 Review 与 Memory 的关系

Review 是正式的作品记录：

```text
Review
├── Rating
├── Status
├── Spoiler
├── Title
├── Content
└── Work
```

它解决：

> **"我对这部作品正式写下了什么评价？"**

Memory 解决：

> **"这段经历中，什么值得被我留下？"**

因此一篇 Review 可以：

```text
独立存在
+
同时成为 Memory 的素材
```

---

# 五、Memory 的长期扩展模型

当前不需要一次实现所有 Memory 类型，但数据结构必须避免堵死未来道路。

```text
Memory
│
├── Review Memory
├── Text Memory
│     └── 一句话感想
├── Media Memory
│     └── 一张截图 / 插图
├── Collection Memory
│     └── "这一天，我把它带回了图书馆"
├── Milestone Memory
│     └── 完成作品 / 重新打开作品
└── Composite Memory
      └── 文字 + 图片 + Work / Character 引用
```

轻量记录、收藏动作生成 Memory 等属于后续扩展。

---

# 六、两种记忆查看维度必须同时存在

这不是二选一。

## 6.1 作品维度

进入某一作品：

```text
CLANNAD
│
├── 世界资料
│
└── 我的记录
      ├── Review
      ├── Memory
      ├── 收藏
      └── Timeline
```

重点：

> **"这部作品在我这里留下了什么？"**

## 6.2 全局维度：记忆回廊

独立的：

> **记忆回廊**

同时提供：

### 主动回忆

用户自由查询：

```text
2022
2023
2024
2025
2026
```

以及：

```text
某作品
某角色
某标签
某时间段
某类记录
```

### 被动重逢

未来提供：

> **"往年今日" / "意外重逢"**

例如：

> "你去年的今天，写下了关于这部作品的一段话。"

---

# 七、"意外重逢"的人格化方向

Tsumugi 已经存在猫娘人格 Layer 2。

因此未来：

```text
记忆触发
    ↓
人格层判断
    ↓
猫娘说出一句话
```

而不是：

```text
系统弹窗：
2025/08/09 有一条 Memory
```

理想状态：

> "诶……你还记得去年今天吗？"

然后用户进入对应 Memory。

必须满足：

- 有真实 Memory 才触发
- 没有命中时不强行制造内容
- 不影响正常首页体验
- 不应成为强制通知
- 不应依赖 LLM 才能工作
- AI 只负责增强表达，而不是创造不存在的记忆

---

# 八、AI 的最终定位

## 8.1 AI 不是 Core

Tsumugi 必须遵循：

> **Core 无 AI 也完整。**

默认用户不应该被要求：

- 注册 AI 服务
- 填 API Key
- 部署 Ollama
- 配置 Embedding
- 配置向量数据库
- 理解 RAG

用户可以直接：

```text
收藏作品
管理作品
写书评
写笔记
保存图片
查看角色
搜索馆藏
查看时间线
管理 Memory
导入 / 导出
```

## 8.2 AI 是 Extension

高级用户可以自行启用：

```text
Ollama
OpenAI-compatible API
其他云端 API
Local Embedding
RAG
Vector Store
AI Assistant
未来 Agent
```

原则：

> **Core 保证人人能用，Extension 给愿意折腾的人提供无限上限。**

---

# 九、RAG 的最终定位

RAG 不再是 Tsumugi 的产品定义，而是：

> **Tsumugi 的高级个人检索能力。**

```text
                         检索台
                            │
              ┌─────────────┴─────────────┐
              │                           │
           世界检索                     我的检索
              │                           │
       External / Connector          Review / Note
       Character / Work              Memory / Media
              │                           │
              └─────────────┬─────────────┘
                            │
                      Personal Search
                            │
              ┌─────────────┴─────────────┐
              │                           │
          Keyword Search             Semantic Search
                                          │
                                      Optional RAG
                                          │
                                   Optional LLM
```

> **现状标注（v1.1 补注）：**「世界检索」（Connector 联合搜索）与「我的检索」
> （本地 RAG）目前是**两套独立入口**，尚未合并为统一的检索台。上图是**目标状态**；
> 合并入口（Personal Search 统一查询）属于后续开发任务，不是已完成能力。

---

# 十、RAG 应该优先回答"关于我的问题"

### 普通数据库问题

> "命运石之门的男主是谁？"

优先：

```text
External Reference
```

### 个人问题

> "我以前怎么看命运石之门？"

优先：

```text
My Review
My Note
My Memory
```

### 混合问题

> "我以前为什么喜欢牧濑红莉栖？"

优先：

```text
我的 Review
我的 Memory
我的 Note
```

必要时补充：

```text
External Character Data
```

---

# 十一、Source Awareness 必须保留

当前项目已经验证：

- `review`
- `note`
- `external_reference`

可以被区分；
- 主观问题可以优先用户书评；
- 前端能够显示"我的书评 / 我的笔记 / 百科资料"等来源。

未来 AI 回答应明确：

```text
根据你的书评：
……

根据你的记忆：
……

根据百科资料：
……
```

必须让用户知道：

> **这是我的记忆，还是世界资料。**

---

# 十二、Memory 与 RAG 的关系

推荐：

> **Memory 是语义容器，RAG 检索其中的素材，而不是强行把 Memory 本身做成一个巨大文本块。**

```text
Memory
│
├── Review ──────→ Review Chunk
├── Note ────────→ Note Chunk
├── Image ───────→ Future Multimodal Chunk
└── Lightweight ─→ Future Memory Chunk
```

Memory 是用户理解世界的组织方式，RAG 是检索这些内容的技术方式。两者不要混成一个概念。

---

# 十三、作品详情页的最终方向

未来作品详情页应逐渐从：

> "数据库详情"

转向：

> **"打开一本属于我的书"。**

推荐形成：

```text
                         WORK

        ┌─────────────────┬─────────────────┐
        │                 │                 │
        │     外部世界    │      我的世界   │
        │                 │                 │
        │     简介        │      收藏       │
        │     制作        │      状态       │
        │     角色        │      评分       │
        │     声优        │      Review     │
        │     系列        │      Memory     │
        │                 │      Timeline   │
        └─────────────────┴─────────────────┘
```

---

# 十四、UI 的最终设计哲学

Tsumugi 不应该成为：

```text
Dashboard
Card
Table
Chat
Status Badge
```

堆叠起来的普通管理工具。

UI 应该让用户产生：

> **"我正在进入自己的图书馆。"**

推荐空间：

```text
检索台
书库
人物档案馆
关系厅
记忆回廊
管理室
```

这些名称应该对应真实的馆内功能，而不是单纯换名。

---

# 十五、真书架与视觉原则

书架应该真正具有：

- 层板
- 书脊
- 系列分架
- 数据驱动的书脊厚度
- 取书
- 打开作品

而不是：

```text
CSS Card Grid
```

伪装成书架。

> **现状标注（v1.1 补注）：**书脊颜色已按标签哈希规则分配（ADR 0019，当时刻意不引入
> 取色库/Canvas 复杂度做真实物理属性驱动）；本节要求的层板线、数据驱动书脊厚度、
> 取书/打开作品交互属于**目标状态**，尚未实现，后续作为书架视图的**增量升级任务**
> 处理，不需要推翻现有配色逻辑，执行时需处理好与 ADR 0037（书脊 hover 取色联动）
> 的整合。

### 视觉层级

**圆角：**

```text
封面 / 图片：可以圆
控制 / 小组件：小圆角
正文 / 面板：弱圆角或近直角
```

**渐变：**

> 主要用于氛围光。

**发光：**

> 一个页面只允许一个主要视觉焦点。

**动画：**

> 默认安静，只在取书、翻页、记忆出现等关键节点使用，并支持 `prefers-reduced-motion`。

---

# 十六、猫娘人格的最终定位

猫娘不是：

> 一个会说"欢迎回来"的装饰角色。

而是：

> **图书馆中的"记忆记录者 / 引导者"。**

她可以：

```text
回应收藏
回应书评
回应重要记录
唤起旧 Memory
提供馆内引导
```

但不能：

```text
随便替用户创造事实
虚构记忆
抢夺用户的主角位置
把整个 UI 变成聊天软件
```

角色关系：

```text
Library = 主体空间
User = 主人 / 记录者
Mascot = 记忆记录者与引导者
AI = 可选智能工具
```

---

# 十七、作品模型的长期方向

当前项目的 Item 模型仍然是已有实现基础。

未来可以逐渐向：

```text
Work
├── type
│   ├── anime
│   ├── manga
│   ├── comic
│   ├── game
│   ├── galgame
│   ├── visual_novel
│   ├── novel
│   └── other
├── external_sources
├── characters
├── creators
├── series
├── tags
└── personal_experience
      ├── collection
      ├── status
      ├── rating
      ├── reviews
      └── memories
```

但这属于后续数据库模型审查与重构任务，不应为了理论完美立即推倒现有 Item 系统。

---

# 十八、个人数据安全与可迁移性

Tsumugi 是个人图书馆。

因此：

> **用户的数据可携带性不是附属功能，而是长期价值的一部分。**

当前项目已经实现：

- JSON 导出
- JSON 导入
- 幂等合并
- 向量数据重建
- Provider 配置引用
- 空实例恢复
- 数据备份入口

这一方向必须继续保留并演进。

---

# 十九、开源原则

Tsumugi 的目标不是：

> "做一个只能由开发者自己运行的 AI Demo。"

而是：

> **让普通用户不需要 AI，也能使用完整的 Tsumugi。**

默认：

```text
Clone / Install
      ↓
启动
      ↓
建立自己的图书馆
      ↓
添加作品
      ↓
开始记录
```

高级用户：

```text
Ollama
↓
Embedding
↓
RAG
↓
Provider
↓
自定义 Connector
↓
未来插件 / Agent
```

全部属于扩展路线。

---

# 二十、当前技术基础

截至现有开发记录，项目已经具备较完整的基础：

```text
Backend
├── FastAPI
├── SQLAlchemy
├── SQLite
├── Chroma
├── 本地 embedding / retrieval
├── RAG
├── 可插拔 LLM Provider（DeepSeek 预设 / 通用 OpenAI 兼容 / Ollama，均已实测）
├── SSRF 防护（Connector / Provider / 代理配置三处，分场景放行回环）
├── 密钥存储（占位符引用 + 直填自动写入 .env 两种方式并存，不落明文）
├── 外部资料本地化 + 参与 RAG 检索（source_type 区分 note/review/
│     external_reference，检索按来源加权）
├── 本地代码级插件系统（plugins/ 目录加载，开源信任模型，无沙箱但风险提示已做）
└── 数据备份/导出/导入（JSON 格式，幂等合并，真实闭环验证过）

External Data
└── Connector Architecture（统一 search/get_detail/normalize 接口）
    ├── Bangumi（真实 OAuth 授权 + 批量导入已验证，含令牌桶限流）
    ├── 萌娘百科（MediaWiki API，wikitext 解析，国内直连）
    ├── VNDB（POST+JSON body 风格，无需 token）
    ├── 声明式自定义源（用户填 API 地址 + 字段映射接入，不执行代码）
    └── 每源可选出站代理（SSRF 校验，区分场景放行回环地址）

Frontend
├── React
├── Tailwind
├── Theme System（四套收敛主题 + 有约束自定义：accent色相/密度/圆角范围）
├── 三种浏览模式（网格 / 书架 / 状态分组列表，含主从详情视图）
├── 命令面板（Ctrl+K，注册表驱动，可扩展）
├── 声优关系图谱（搜索驱动的邻域视图，非全局大图）
├── 活跃度热力图（年度总结）
├── 封面动态取色氛围（详情页 + 卡片hover + 书脊hover，统一视觉语言）
├── 批量操作 / 右键菜单 / 快捷键 / Toast 反馈
├── 首页"神殿"空间（ADR 0039）+ 猫娘人格台词系统（ADR 0040，Layer 2
│     第一批：固定台词库，场景触发，未接 LLM 实时生成）
├── Custom Layout
└── Electron Shell

Engineering
├── pytest
├── Vitest
├── Build Verification
├── ADR-lite
├── Backup / Restore
└── Electron 独立打包（PyInstaller）仍未完全解决（transformers 延迟导入
    机制冲突，已按止损点停止）；Docker 部署路径已完整验证，是当前实际
    可用的主要分发方式
```

现有记录还显示：

- LLM Provider 已可插拔；
- Ollama 已实测流式问答；
- 无 Provider 时 AI 自动降级而不影响检索等核心功能；
- RAG 已能够区分"我的书评"和外部百科资料；
- 数据导入导出已经形成真实闭环；
- Electron / Web 共用前端；
- 项目已有持续的决策记录机制。

这些能力应作为重构基础，而不是重新实现。

---

# 二十一、最终系统架构

```text
                              Tsumugi
                                 │
              ┌──────────────────┴──────────────────┐
              │                                     │
          Library Core                         Optional AI
              │                                     │
      ┌───────┼────────┐                    ┌───────┼────────┐
      │       │        │                    │       │        │
     Work   Review   Memory                LLM    RAG    Embedding
      │       │        │                    │       │        │
      │       └────────┼────────────────────┘       │        │
      │                │                            │        │
      ├── Character    │                            │        │
      ├── Creator      │                            │        │
      ├── Series       │                            │        │
      ├── Tags         │                            │        │
      └── External     │                            │        │
                       │                            │        │
                    Experience                  Personal
                       │                        Retrieval
                       │                            │
                  ┌────┴────┐                ┌──────┴──────┐
                  │         │                │             │
                Media    Timeline          Search       AI Answer
                  │         │                │             │
                  └────┬────┘                └──────┬──────┘
                       │                            │
                       └────────────┬───────────────┘
                                    │
                               Library UI
                                    │
       ┌────────┬─────────┬────────┼────────┬──────────┐
       │        │         │        │        │          │
     检索台    书库    人物档案馆  关系厅  记忆回廊   管理室
```

---

# 二十二、最终搜索体系

## Level 1：精确查询

```text
CLANNAD
```

## Level 2：结构化查询

```text
我收藏的 Galgame
我完成的作品
我给五星的作品
2025 年看过的动画
```

## Level 3：个人全文 / 语义检索

```text
我以前写过哪些关于孤独的东西？
```

## Level 4：个人记忆理解

启用 AI 后：

```text
为什么我以前喜欢这部作品？

我过去几年对这类作品的看法有没有变化？

帮我找出我最常提到的角色。

我以前什么时候开始喜欢这个角色？
```

Level 4 是增强能力，不是基础功能依赖。

---

# 二十三、开发优先级

不建议一次性重构全部系统。

## Phase A：Memory Core

```text
Memory 数据结构
Review → Memory 关联
Review 创建 / 发布 → 自动 Memory
```

目标：

> 让"作品与我的联系"真正成为可存储的数据。

## Phase B：作品记忆时间轴

```text
Work
  ↓
My Memories
  ↓
按时间排列
```

目标：

> 第一次真正让用户看到"这部作品在我这里留下了什么"。

## Phase C：记忆回廊基础版

```text
所有 Memory
↓
按时间浏览
↓
筛选
↓
查询
```

第一版只做自由查询，不加入复杂惊喜机制。

## Phase D：Memory 扩展素材

逐步加入：

```text
一句话 + 截图
图片
收藏时刻
完成时刻
重新打开作品
```

## Phase E：意外重逢

```text
往年今日
↓
人格层
↓
猫娘唤起
```

## Phase F：作品模型泛化

审查当前 Item 模型后，再逐步支持：

```text
Anime
Manga
Comic
Game
Galgame
Visual Novel
Novel
Other
```

## Phase G：Personal RAG

最后再让：

```text
Memory
Review
Note
External Data
```

进入更完整的个人语义检索体系。

---

# 二十四、开发时必须遵守的原则

### 原则 01
> **Work 是核心馆藏对象，Book 是 UI 隐喻。**

### 原则 02
> **Tsumugi 的核心价值是"作品与我的联系"。**

### 原则 03
> **世界轴与我的轴必须保持清晰分离。**

### 原则 04
> **二次元数据库描述世界，Tsumugi 记录我与世界的关系。**

### 原则 05
> **Experience 是语义聚合，不是实体表。**

### 原则 06
> **Memory 是独立容器，不是 Review 的视图。**

### 原则 07
> **Timeline 是查看方式，不是独立数据实体。**

### 原则 08
> **Review 保持独立机制，同时允许进入 Memory。**

### 原则 09
> **AI / RAG 必须是可选能力。**

### 原则 10
> **没有 AI，Tsumugi 仍然必须是完整产品。**

### 原则 11
> **AI 不得创造不存在的用户记忆。**

### 原则 12
> **AI 回答必须尽可能区分用户资料与外部资料来源。**

### 原则 13
> **图书馆是信息架构，不是换皮。**

### 原则 14
> **UI 应该让用户感觉自己在进入一个空间，而不是操作一个后台。**

### 原则 15
> **视觉隐喻服务于信息，不允许装饰压过内容。**

### 原则 16
> **默认动画安静，并尊重 reduced-motion。**

### 原则 17
> **用户数据必须可导出、可迁移、可长期保存。**

### 原则 18
> **重大架构决策必须留下 ADR-lite 记录。**

---

# 二十五、哪些事情暂时不要做

```text
不要：
├── 强制 AI
├── 强制云端 API
├── 强制 Ollama
├── 一开始做复杂 Agent
├── 一开始做多模态 RAG
├── 一开始做复杂知识图谱
├── 一开始迁移生产级向量数据库
├── 给插件系统做沙箱隔离（已有结论：本地文件加载 + 开源信任模型 +
│     风险提示已足够；插件系统本身已完成，这条特指不做沙箱工程）
├── 为了支持所有作品类型立即推倒 Item
└── 为了"二次元感"继续堆视觉特效
```

这些可以存在于 Extension / Future Roadmap，但不能反过来绑架 Core。

---

# 二十六、最终产品闭环

```text
进入图书馆
      ↓
发现 / 搜索作品
      ↓
把作品收入书库
      ↓
浏览作品世界
      ↓
开始自己的经历
      ↓
观看 / 阅读 / 游玩
      ↓
写下 Review
      ↓
留下 Memory
      ↓
保存截图 / 插图
      ↓
记录人物与作品关系
      ↓
几年后再次打开
      ↓
看到过去留下的痕迹
      ↓
重新理解当时的自己
```

最终：

```text
作品
  ↓
经历
  ↓
记录
  ↓
记忆
  ↓
时间
  ↓
再次相遇
```

这才是 Tsumugi 的核心循环。

---

# 二十七、最终一句话

如果以后向别人介绍 Tsumugi：

> ## **Tsumugi 是你的二次元私人图书馆：收藏作品，也收藏与作品相遇时留下的自己。**

进一步解释：

> **它用二次元数据库帮助你认识作品，用个人记录保存你与作品的联系，用 Memory 保存值得回望的时刻，并通过可选的语义检索、RAG 与 AI，在多年以后帮你重新找回那些已经忘记的东西。**

---

# 二十八、最终判断

Tsumugi 不应该成为：

> **一个带有二次元主题的数据库。**

也不应该成为：

> **一个套着图书馆 UI 的 AI Chat。**

更不应该成为：

> **一个没有 AI 就无法工作的 RAG Demo。**

它应该成为：

> ## **一个以作品为锚点、以个人经历为核心、以记忆为长期价值的二次元私人图书馆。**

其中：

```text
作品数据库
    ↓
让它知道"世界"

个人记录
    ↓
让它知道"我"

Memory
    ↓
让它记住"发生过什么"

Timeline
    ↓
让时间重新连接这些事情

图书馆 UI
    ↓
让这些东西拥有一个可以进入的空间

RAG / AI
    ↓
在用户需要的时候，
帮助他把已经留下的东西重新找回来
```

---

# 二十九、最终开发判断标准

从此以后，任何新的：

- 数据库设计
- API
- UI
- Agent Prompt
- RAG
- AI Provider
- Memory
- Connector
- 插件
- 页面

都应该先回答：

> **"它是在增强 Tsumugi 作为私人图书馆的能力，还是只是在增加一个普通软件功能？"**

如果只是增加功能，而不能增强：

> **作品 × 我的经历 × 我的记忆**

那么它就不应该成为 Core。

---

> **Tsumugi 的目标不是帮你记住所有作品。**
>
> **而是让你多年以后，仍然能够找到当时的自己。**

---

# 【v1.1 修订记录】

对照"开发流程简报.md"真实开发记录与已有 ADR，本版相对 v1.0 仅做四处修订：

1. **第二十节「当前技术基础」**：Connector 现状严重滞后。由只列 Bangumi 修正为
   完整的 Connector 树（Bangumi OAuth 批量导入 / 萌娘百科 / VNDB / 声明式自定义源 /
   每源可选出站代理），并补齐 Backend / Frontend / Engineering 三块已实测的遗漏项
   （SSRF 防护、密钥存储、外部资料本地化参与 RAG、本地插件系统、备份导入导出、
   三种浏览模式、命令面板、声优邻域图谱、活跃度热力图、封面取色氛围、神殿首页 +
   猫娘台词系统、四套主题、Electron 打包现状等）。
2. **第九节「RAG 的最终定位」**：检索台架构图标注"现状 = 世界检索与我的检索仍是
   两套独立入口，合并检索台是目标状态"，避免被误读为已完成能力。
3. **第十五节「真书架与视觉原则」**：补充现状标注——书脊颜色已按标签哈希分配
   （ADR 0019），层板/数据驱动厚度/取书交互是目标状态，作为增量升级任务，并需与
   ADR 0037（书脊 hover 取色）整合，不推翻现有配色。
4. **第二十五节「哪些事情暂时不要做」**：修正"一开始做插件沙箱"的歧义表述——插件
   系统本身已完成（本地加载 + 开源信任模型 + 风险提示），本项特指不做沙箱隔离工程。

其余章节（产品定位、世界轴/我的轴、Memory 定义、Phase 排期、十八条原则、产品闭环）
核校无误，与 v1.0 保持一致。

---

*路径说明：本文放于仓库 `docs/`（而非 `项目简报\Tsumugi\`）是因为 01/02/03 号开发
提示词与 AGENTS.md 都直接引用 `docs/product-brief-v1.1.md` 作为可执行的开发基准；
原始讨论稿（v1.0 / v0.2 / v0.1 / 现状校验附录）仍保留在 `项目简报\Tsumugi\` 供回溯。*
