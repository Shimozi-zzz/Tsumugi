# 0089 · Phase 10-1-A-3：浏览面「我的记录」经历密度标记

日期：2026-08-12
状态：已接受
基准：Phase 10-1-A-0 审计（Experience Loop 断点②：浏览面无法提前知道哪些作品已有「我的经历」）、
Phase 8-9 Design Language、简报约定 `GET /memories?limit=500` 全量拉取

## 一、决策

在浏览面（Library Grid 卡片 + Bookshelf 书脊）提供极轻量的经历密度标记：有 Memory/Review
的作品显示 `§ N 条我的记录`，无记录保持干净。**不新增 API/字段**——复用 DesktopView 已有的
`fetchAllReviews` 与 `GET /memories?limit=500`（简报既有惯例），前端建 per-item 计数映射。

## 二、做法

- **DesktopView.jsx**：新增 `allMemories`（fetchMemories limit 500）+ `recordCountOf` memo
  （reviews + memories 计数 Map）；传入 ArchiveCard 与 Bookshelf。
- **ArchiveCard.jsx**：`recordCountOf(it) > 0` → metadata 行追加 `§ {n} 条我的记录`
  （quiet mono，与 ─ 编目/来源/记录 同级；无 pill/badge/背景）。
- **Bookshelf.jsx**：`recordCountOf(it) > 0` → 书脊顶部极轻 mono `§{n}`（`.shelf-book-record`，
  aria-hidden 纯装饰；不覆盖书名/不改布局）；`data-narrow` 与移动端（<640px）隐藏。
- 视觉约束：mono / ink-2 混合 / 小字号；无 whiteOnAccent / accent-filled / gradient / glow /
  rounded-full / badge。

## 三、验证

- vitest **289 passed**（285 + 4：ArchiveCard 有记录显示/无记录不显示/未传 prop 不显示+点击
  保持；Bookshelf 有记录 § 标记/无记录无标记+点击保持）；build 通过。
- 真实浏览器（真实库 63 部）：Grid **58/63** 卡片显示「§ N 条我的记录」（数据驱动）；
  Bookshelf **58** 本书脊显示 `§N`；1920/1440/1024/768/390 全 `hOverflow=false`；有记录
  可识别、无记录干净。截图 `mem101a3_1920/1440/1024/768/390.png`。
