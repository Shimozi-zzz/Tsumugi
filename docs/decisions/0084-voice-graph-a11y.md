# 0084 · Phase 8-2-A：Voice Graph 节点键盘可访问性

日期：2026-08-12
状态：已接受
基准：Phase 8-2-0 审计（SVG 节点"鼠标可点但键盘不可达"，64 个 g 无 tabindex/role/focus）

## 一、决策

只修 Voice Graph 可交互节点的键盘可达与键盘激活语义（最小独立 accessibility 小步）。
不动 Voice 视觉语言（search/pill/accent 按钮/radius 等留待 8-2-B/C）。

## 二、做法

- **交互节点 + 键盘语义**（VoiceGraphView.jsx）：
  - ego 作品 `g`、共同出演声优 `g`、角色小圆点 `circle`；overview 作品 `g`、角色
    `circle`、声优 `g`——统一加 `role="button"`、`tabIndex={0}`、`aria-label`（复用现有
    `<title>` 语义：作品标题 / `角色名（声优）` / `声优：名字`），`<title>` 保留。
  - **Enter / Space 激活**：`activate(fn)` onKeyDown（`Enter` 或 `" "` → preventDefault
    防页面滚动 + 调用与鼠标 click **同一业务函数**）；鼠标 click 与键盘共用
    `onOpenWork?.(id)` 与 `selectActorByName(name)`（抽取复用，不复制业务）。
- **focus-visible 环**（index.css）：`svg g:focus-visible > circle` /
  `svg circle:focus-visible` → accent 描边 2.5px（无 glow/gradient/layout shift）；同时
  `outline: none` 抑制默认环。中心声优圆（非交互）不设 tabindex。
- 视觉冻结：搜索框/actor pill/实心 accent 按钮/graph 容器 radius/节点视觉/布局 全不动。

## 三、验证

- vitest **281 passed**（275 + 6：role/tabindex/aria-label 语义、Enter/Space=与 click 同
  业务结果且不重复触发、Enter 激活声优切换邻域、不可交互元素无 role=button、mouse click
  不变）；build 通过。
- 真实浏览器（真实库，ego 图）：**interactive=64 / focusable=64 / named=64**；5 视口
  `hOverflow=false`；真实 Tab 可到达 SVG 节点；鼠标点击节点 → 书库 ✓；`:focus-visible`
  环规则已就位（离屏 harness 不激活 :focus-visible 匹配，需真实浏览器目检一次）。截图
  `voice82a_1920/1440/1024/768/390.png`。
