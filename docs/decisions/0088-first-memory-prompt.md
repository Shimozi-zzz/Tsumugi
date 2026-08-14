# 0088 · Phase 10-1-A-1：Work Detail 第一条记录引导

日期：2026-08-12
状态：已接受
基准：Phase 10-1-A-0 审计（Experience Loop 断点①：拥有作品但不知道可以留下第一条记录）、
Phase 4 mc-* composer

## 一、决策

只增强 Work Detail「我的记忆」的空态发现性：当某作品 **零记忆且零书评** 时，在 composer
上方显示一行 quiet 引导（`.mc-empty-hint`），把"这里可以留下第一条记录"显性化。Composer
创建/情绪/附图/里程碑/MemoryTimeline 逻辑全部不变；数据/API 零改动。

## 二、做法

- `ItemDetailPanel.jsx`：
  - fetch effect 改为 `Promise.all([reviews, memories])` + 新增 `memReady` 状态（数据就绪
    后才判断，避免空态引导闪烁）；
  - `memReady && memories.length === 0 && reviews.length === 0 && detail.source !== "local"`
    → 渲染 `.mc-empty-hint`（serif 12px ink-2 quiet 行）于 composer 上方。
- `index.css`：`.mc-empty-hint`（安静、无 badge/pill/背景）。
- 测试 +2：零记录显示引导（且 composer 仍在）；已有书评不显示引导。

## 三、验证

- vitest **285 passed**（283 + 2）；build 通过。
- 真实浏览器（真实库，遍历 8 部作品）：3 部零记录作品显示引导、5 部有记录的不显示；
  引导样式 = serif 12px / ink-2 / quiet；hOverflow=false。截图 `mem101a1_1440.png`。
