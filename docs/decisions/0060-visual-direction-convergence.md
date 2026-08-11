# 0060 · 视觉方向收敛：仅保留编目抽屉（适配经典三栏 / 非对称档案室）

日期：2026-08-10
状态：已接受
说明：用户定案——**视觉方向仅保留「编目抽屉」（ADR 0056 默认设计系统）**；该风格同时
适配「经典三栏」与「C 非对称档案室」两个外壳。本轮将 ADR 0055 探索产物正式收敛（非新增功能）。

## 一、网格视觉方向收敛：仅编目抽屉

- 移除 `GridConcepts.jsx`（A 深夜书房 / B 编目卡片抽屉 / C 展览橱窗 三个探索组件 +
  `GridConceptSwitcher` + `parseConcept`）及对应测试 `grid-concepts.test.jsx`。
- `DesktopView`：移除工具栏「视觉方向」开关、`gridConcept` 状态、`?concept=` URL 直通与
  localStorage `tsumugi-grid-concept`；网格分支仅保留经典档案卡（ArchiveCard 编目行
  `NO.xxxx · 来源`，ADR 0054/0056）即编目抽屉正式形态。
- `index.css`：移除 ADR 0055 探索块（`.grid-concept-switch`、`.concept-a/b/c*` 全部规则）。
- 理由：编目抽屉已转正为唯一设计系统（0056）；A/C 主张经对比未采纳，开关徒增维护面。

## 二、两个外壳均为编目抽屉风格

- 经典三栏：书库网格即编目抽屉档案卡（编目号/来源徽标/衬线标题/近直角/纸感 token）。
- C 非对称档案室（ShellC，ADR 0057/0059）：导航 rail 与房间内容均沿用编目抽屉 token
  （--accent/--accent-soft/--panel-border/--font-mono 等），书库房间直接渲染 ArchiveCard
  编目抽屉卡片。两个外壳同一视觉方向，无第二套视觉语言。

## 三、测试与实测

- vitest **229 passed**（删 6 例 grid-concepts；其余外壳/卡片测试不依赖概念开关）。build 通过。
