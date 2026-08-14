# 0083 · Phase 8-1-B：Character Archive PageHeader 控件语言收敛

日期：2026-08-12
状态：已接受
基准：757b68b（Phase 8-1-A）、Phase 8-0 审计遗留 P3

## 一、决策

只收敛 Character Archive PageHeader 的两个控件——「声优关系」「刷新」——从 SaaS 按钮
（白字实心 accent / rounded-xl）改为 **quiet control**：transparent + hairline +
`--radius-control`，hover=surface-2、focus-visible 清晰。功能/文案/位置/交互全冻结。

## 二、做法

- `DesktopView.jsx`：两个按钮去掉 inline `backgroundColor: var(--accent), color: #fff`
  / `accent-soft` 与 `rounded-xl`，改用 `.character-archive-action`（声优关系加
  `-accent` 修饰色）；onClick 链不变（声优关系 → setVoiceFocus(null)+setSection("voice")；
  刷新 → setCharRefreshKey(k+1)）；补 `type="button"`。
- `index.css`：新增局部 `.character-archive-action`（transparent + hairline +
  radius-control；hover surface-2 + 微 accent 边；`:focus-visible` accent outline）。
  无新 token、无 rounded-full/rounded-2xl/渐变/glow。

## 三、验证

- vitest **275 passed**；build 通过。
- 真实浏览器（真实库）：1920/1440/1024/768/390 全 `hOverflow=false`；header 按钮
  whiteOnAccent=0、pill=0、r2xl=0、rxl=0、radius=**8px**（radius-control）、bg
  transparent、border=panel-border；`.char-entry` radius 6px 不变（8-1-A 未破坏）；
  点击「声优关系」→ 进入声优图谱 ✓、「刷新」→ 重新拉取角色 ✓；真实 Tab 遍历正常；
  `:focus-visible` 规则已按既有模式落地（离屏无法复现 outline 渲染，需真实浏览器目检）。
  截图 `char81b_1440.png`。
