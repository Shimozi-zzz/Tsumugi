# 0080 · Bookshelf-2.5：视觉丰富度（姿态微差 / 架体内影 / 明度节奏）

日期：2026-08-12
状态：已接受
基准：ADR 0079（Bookshelf-2 结构）、Bookshelf-2.5 审计结论「结构正确但偏单调」

## 一、决策

Bookshelf-2 结构已成立，本阶段只增加「空间感 / 层次感 / 收藏感 / 轻微不规则」，
不重做结构/布局/共享架/交互；数据逻辑与 bookshelf.js 零改动，无新依赖。

## 二、视觉丰富度来源（均由 it.id 确定性派生，无 Math.random）

1. **书本姿态 bookPose()**（Bookshelf.jsx 新增纯函数）：
   - 高度微差 ±8px（210±8 → 202..218；移动端 172±8 → 164..180，CSS `calc(var(--bh) - 38px)`）；
   - 宽度微差 ±2px（叠加 bookWidth，保留 spineThickness 相对关系 → 21..44px）；
   - 极少数书微倾 ±0.6°（20 项 tilt 表中约 1/4 非零，`--tilt` + `transform-origin: 50% 100%`，
     书底站层板、顶缘轻靠邻书）；hover 保留 `rotate(var(--tilt)) translateY(-5px)`。
2. **明度节奏**：spineColorVaried 增加 ±3% 明度抖动（色相 ±12° 不变）→ 63 本 56 种
   微差色（同分类仍是"22 本不同的紫书"，非整块紫墙、也非彩虹）。
3. **架格内影（CSS）**：`.shelf-case` 顶部留白 26px + `::before` 顶部内影（暗示上方还有
   层板）+ `overflow-x: clip`（防微倾造成横向滚动）；`.shelf-books` 顶部 inset 软影
   （书后方 recess）；`.shelf-board` 前缘底部略深（厚度感）。

## 三、保留/不改

- 共享架布局、fit-content 匣、书脊最小 24px、hover 抽书/CoverAmbient/preview、点击进
  详情 / selectMode / context menu / aria-pressed 全不变；
- 分类索引（serif+mono+hairline）不动；不新增 badge/pill/大阴影/渐变背景/图标。

## 四、验证

- vitest **273 passed**（270 + 3：bookPose 确定性/范围/非全直立、渲染 --bh/--tilt/--sw
  确定性 + 范围、倾斜书仍可点击）；build 通过。
- 真实浏览器（Electron 离屏 + 真实库 63 册）：1920/1440/1024/768/390 全
  `hOverflow=false`；书宽 21–44px、高 202–218px（17 种）、16/63 本微倾（≤0.6°）、
  56 种微差色；hover 最左/最右/最窄/最宽（1440+390）均无截断；点击进「作品档案」、
  context menu、selectMode 63 标记+aria-pressed、网格 63 卡、列表 3 组 全正常；
  无 JS 错误。截图 `bookshelf25_1920/1440/1024/768/390.png`。
