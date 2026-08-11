# ADR 0076 — Work Detail Encounter Chronicle

## Status

Accepted（Phase 3-2-C-0 数据规则层；UI 实现属 Phase 3-2-C-1，另排期）

## Context

Work Detail 叙事正在成形：作品本身 → 这个世界 → 我与它 → 相遇纪事 → 我的记忆。
「相遇纪事」需要一条"我与这部作品逐渐形成关系"的事件叙事。但当前系统没有统一的
作品关系时间线，且不能确定数据能证明哪些关系事件——本 ADR 先回答：**Tsumugi 到底
知道什么**，再定义未来 UI 的数据规则。

## Problem

- 没有 encounter 表 / 关系时间线；
- 各关系事实分散在 Collection / Review / Memory（含 milestone）；
- 时间字段语义不同（occurred_at / created_at / added_at / updated_at），不能混用；
- 容易把"最早用户痕迹"误称为"第一次遇见"。

## Audit Result（真实代码核对）

- **Collection**（`app/models.py:189`，P2/ADR 0046）：`item_id/status/favorite/added_at`。
  `added_at` = 收藏入库时间（新收藏=now，历史回填=item.created_at），nullable。
  Work Detail 已通过 `ItemDetailOut.collected_at(=collection.added_at)`/`collection_status`/
  `favorite` 获得（`routes.py:1478`）。
- **Memory**（`app/models.py:121`，ADR 0041/0047）：`source_type ∈ review/collection/text/
  milestone`、`source_ref`、`occurred_at`（nullable=False，注释："这段记忆发生的时间"）、
  `summary/emotion/created_at(server_default now)`、`media[]`。
  `occurred_at` 的赋值语义（`app/memories.py`、`app/collections.py`）：
  - review 记忆 = `review.created_at`（memories.py:62）；
  - collection 记忆 = `now`（collections.py:75）；
  - text/milestone 直接记忆 = `now`（memories.py:166，可传 occurred_at）；
  - 自动完成 milestone = `now`（collections.py:93）。
- **Review**（`app/models.py:100`，ADR 0010/0040）：`created_at(server_default now)`、
  `updated_at(onupdate now)`、`rating(0-10)`、`status`、`spoiler`。
- **Milestone** = `Memory(source_type=milestone)`：自动（状态→看完，ADR 0062，
  summary"这一天，我把《{title}》看完了"）+ 手动（composer"完成了这部作品。"/
  "重新打开了这部作品。"）。**完成 vs 重新打开没有结构化子类型**，仅能由 summary 文本
  区分——文本推导，非结构化事实。
- **Work Detail 数据流**：`/items/{id}/detail`（含 collection 字段）+ `/items/{id}/memories`
  （MemoryTimeline 已取）+ `/items/{id}/reviews`（书评）。不修改 API 即可获得全部所需数据。

## Data Sources

| 来源 | 可证明事件 | 事实时间字段 |
|---|---|---|
| Collection.added_at | 带回书架 | added_at |
| Review.created_at | 写下书评 | created_at（非 updated_at） |
| Memory(source_type=text).occurred_at | 留下一份记忆 | occurred_at |
| Memory(source_type=milestone).occurred_at | 一个里程碑（完成/重新打开） | occurred_at |

## Event Mapping

纯前端 `buildEncounterEvents({collection, reviews, memories})`（`frontend/src/encounter.js`）：

| 事件 | 数据来源 | 时间字段 | 是否明确事实 | 未来允许表达 |
|---|---|---|---|---|
| collection（带回书架） | Collection.added_at | added_at | 是 | "带回书架" |
| review（写下书评） | Review.created_at | created_at | 是 | "写下书评" |
| memory（留下一份记忆） | Memory text.occurred_at | occurred_at | 是 | "留下一份记忆" |
| milestone（里程碑） | Memory milestone.occurred_at | occurred_at | 是（发生过）；完成/重开仅为文本标签 | "完成这段旅程 / 重新打开"（用 summary 文本） |

**排除**：review/collection 类型记忆（与主事件重复）；review.created_at 缺失；added_at 缺失。

## Timestamp Rules

- Collection → `added_at`；
- Review → `created_at`（**禁用 updated_at**：updated_at=最后编辑，不是"写下"时刻）；
- text/milestone Memory → `occurred_at`（**禁用 created_at**：created_at=系统写入时间，
  不是记忆实际发生时间；但 review/collection 记忆的 occurred_at 恰由其主源时间决定）。

## First Encounter Policy

**不支持「第一次遇见」。**

依据：最早用户痕迹（最早 memory.occurred_at / review.created_at / added_at 的 min）只能
证明"系统中存在的最早记录"，不能证明用户"第一次接触作品"——用户可能更早接触但未留痕。
**禁止** `min(最早痕迹) = 第一次遇见`。
未来 UI 若展示，用更诚实的表达：如"最早记录 / 最初留下的痕迹 / 最早记忆"（文案在 UI 阶段定）。
原则：宁可少一个事件，也不让私人档案说谎。

## Fact vs Inference

- 事实：带回书架（added_at）、写下书评（created_at）、留下一份记忆（occurred_at）、
  一个里程碑发生过（milestone.occurred_at）。
- 推断（仅文本层，非结构化）：milestone 的"完成 vs 重新打开"取自 summary 文本；
  "最早记录"不表示"第一次遇见"。

## Missing Data

- 无 Collection → 无「带回书架」；无 Review → 无「写下书评」；无 text Memory → 无
  「留下记忆」；无 milestone → 无里程碑；全部缺失 → 返回 `[]`，UI 允许整章隐藏。
- 不生成"暂无事件 / 0 events / 空占位卡"。

## Duplicate Events

同日多个独立事件（Collection+Review+Memory）**各自保留**，View Model 不聚合不丢弃；
视觉聚合若需要，留给 Phase 3-2-C-1 UI 层决定。

## Ordering

`occurredAt ASC`（最早 → 最近）：表达"关系逐渐形成"，而非后台操作日志。
同时刻按 `类型序 + 来源 id` 稳定排序。

## View Model

`EncounterEvent = { id, type, occurredAt, title, source, metadata }`（纯前端，
`frontend/src/encounter.js`）。非数据库模型、非 schema、无需 API/迁移。

## Non-Goals

- 不修改 API / 数据库 / schema / 字段；
- 不新增 first_seen_at / encounter 表 / 后端 endpoint；
- 不修改 Collection / Memory / Review 语义、Review Studio、MemoryTimeline、
  MemoryTypeTag、ItemDetailPanel 视觉结构；
- 不实现相遇纪事 UI（Phase 3-2-C-1）；
- 不新增 Timeline UI 组件。

## Consequences

- Phase 3-2-C-1 只需调用 `buildEncounterEvents` 渲染；事件"先证明后显示"；
- 里程碑标签来自 summary 文本，不伪造结构化子类型；
- 整个章节可在无事件时自然隐藏。
