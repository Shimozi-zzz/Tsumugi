# 0041 · Memory Core：记忆核心数据结构（Phase A）

日期：2026-08-09
状态：已接受
基准：docs/product-brief-v1.1.md（v1.1 世界轴/我的轴、Memory 独立容器）+ prompts/01_PhaseA

## 一、范围

本轮唯一目标：**让"作品与我的联系"真正成为可存储的数据**。只做数据层：
- 新增 `Memory` 表 + `ensure_schema` 风格迁移（新表走启动时 `create_all`，旧库自动补建）；
- Review 创建/发布时自动生成 Memory 条目；编辑/删除 Review 时同步/删除对应 Memory；
- 两个后端接口（按 item 查询、全局筛选），为 Phase B/C 做准备。

**本轮不做**（Phase B/C/D 范围）：时间轴展示、记忆回廊页面、轻量记录/收藏时刻等
新素材类型、AI 检索记录写入 Memory。

## 二、Memory 表字段设计（为未来扩展预留了什么）

```text
memories
├── id
├── item_id          → 关联哪个作品（FK items.id）
├── source_type      → 素材来源类型；本轮 = review；预留 text / image /
│                      collection / milestone（**不做白名单硬校验**，防止把表
│                      设计成"只能装 Review"）
├── source_ref       → 指向具体来源记录的引用（review 时 = Review.id）
│                      多态引用，**不设外键**（不同 source_type 指向不同表）
├── occurred_at      → 这段记忆发生的时间（时间轴排序用；review = Review.created_at，
│                      而非入库时刻）
├── summary          → 简短展示摘要（见下"是否加冗余 summary 字段"）
└── created_at
```

关键取舍：
- **source_ref 不设外键**：review 指 reviews 表，未来 text/image 可能指向别处或
  无主记录，外键会把多态锁死；由业务层保证引用一致性（Review 删除时同步删 Memory）。
- **occurred_at 与 created_at 分离**：记忆的"发生时间"（写作时刻）与"入库时间"是
  两回事，时间轴必须按 occurred_at 排；这是"记忆"而非"日志"的本质区别。
- **扩展性验证**：v1.1 的 Collection Memory（"这一天，我把它带回了图书馆"）未来
  可直接用 `source_type=collection + source_ref=item_id` 落进同一张表，无需改结构。

## 三、是否加冗余 summary 字段：加（理由）

- Review 内容可能很长（Markdown 正文），列表/时间轴展示时**逐条实时关联查询完整
  内容**会产生 N+1 查询与不必要的传输；
- summary 只存展示所需的最小信息（标题优先，否则内容首行截断 40 字 + 省略号）；
- 代价是编辑 Review 时需要同步（已实现 `sync_review_memory`，幂等），换来列表
  轻量与前端零额外请求，对本项目体量是划算的冗余。

## 四、Memory 不参与独立 RAG 处理（确认）

v1.1 第十二节明确：**Memory 是语义容器，RAG 检索其中的素材，而不是强行把 Memory
本身做成一个巨大文本块**。因此：
- 不为 Memory 表设计 embedding/chunk 逻辑；
- 底层 Review 依然按现有 `source_type=review` 机制正常参与检索（ADR 0025），
  检索层不感知 Memory 这个概念；
- 未来若有新素材类型需要检索，是在那个素材上建 chunk，而不是 Memory 表。

## 五、Review 生命周期与 Memory 的一致性（同一事务）

- **创建**：`reviews.create_review` 在 `flush()` 拿到 review.id 后
  `memories.ensure_review_memory(review, db)`（幂等），与 Review 同事务提交——
  向量写入失败回滚时 Memory 一并回滚；
- **编辑**：`update_review` 提交前 `sync_review_memory` 同步摘要（只更新已存在
  的记录）；**不走 create_review 的 Review（如 Bangumi 导入的状态/评分记录）编辑时
  不会凭空造 Memory**——那是"收藏同步"而非"用户写下的记忆"，Collection Memory 属
  Phase D；
- **删除**：`delete_review` 删除向量后先删 Memory 行再删 Review，不留孤儿；
- **删除作品**：`Item.memories` 关系带 `cascade="all, delete-orphan"`，作品删除时
  级联清掉全部 Memory。

## 六、历史数据回填：本轮不做（有意）

存量 Review 不会自动补 Memory 行。理由：本轮是数据层，回填属于一次性数据任务且
摘要生成要批量跑；Phase B（作品时间轴）上线前如需让旧书评也出现在时间轴里，再单独
做一次回填任务。已在 ADR 与简报中明确，避免误以为漏实现。

## 七、接口（为 Phase B/C 准备）

- `GET /items/{item_id}/memories`：某作品全部记忆，`occurred_at` 倒序（Phase B 时间轴）；
- `GET /memories?item_id=&start=&end=&skip=&limit=`：全局查询，支持 ISO 时间 / 纯日期 /
  年份（年份作 end 时按次年 1 月 1 日 exclusive 处理，便于"按 2023/2024/2025"筛选，
  Phase C 记忆回廊）。

## 八、测试与实测

- pytest **403 passed**（+17 `test_memories.py`：迁移建表、创建自动生成、摘要标题/截断、
  编辑同步、meta-only 不变、无 Memory 的 Review 编辑不凭空造、删除级联、embedding 失败
  同事务回滚、按 item/时间范围/分页查询、API CRUD 流程与年份筛选），覆盖率 86.87%。
- 实测见简报（真实后端创建/编辑/删除 Review，确认 Memory 正确生成/同步/删除）。
