# 0077 · Phase 7-1B：移除非对称档案室外壳（ShellC 全量下线）

日期：2026-08-11
状态：已接受
基准：ADR 0057/0059/0064/0065/0067（ShellC 引入与整合）、ADR 0066（夜书房 token）

## 一、决策

删除 C 非对称档案室外壳（ShellC）及全部外壳切换机制，Classic 三栏外壳成为唯一外壳。
`?shell=` 查询参数、`tsumugi-shell-concept` localStorage、设置页「应用外壳」开关全部移除。

## 二、理由

- ShellC 与「夜书房 · 经典三栏」目标视觉长期重叠：Phase 7-0 确认 Ask 区等既有
  Classic 视觉已足以承载文献式体验，非对称格局未产生独特价值，反增双壳维护面
  （双份房间渲染器 / 双份导航 / 双份测试 / 切换状态）。
- 产品收敛方向是"一个图书馆"：去掉外壳开关后，空间结构不再可被用户误入"另一套
  布局"，CommandPalette/导航/设置均为单一来源。
- 移除不影响任何数据/API/组件复用：ShellC 的房间内容全部是 Classic 组件 +
  ADR 0068 书库空间 的组合，删除的是"另一套外壳壳层"。

## 三、变更清单

- 删除 `AppShells.jsx`（ShellC / ShellContent / ShellLibrary / ShellBackup /
  ShellSwitcher / SHELL_CONCEPTS / parseShell）与 `app-shells.test.jsx`（9 个用例）。
- `DesktopView.jsx`：移除 shellConcept 状态 / URL+localStorage 读取 / changeShellConcept
  / `?shell=` 分支（classic 恒渲染）/ 设置页「应用外壳」块；import 清理。
- `index.css`：删除 `.shell-switcher` / `.shell-grid` / `.shell-c*` 全部样式块。
- 注释清理：ItemDetailPanel / CommandPalette 中的 ShellC 提及。

## 四、验证

- vitest **264 passed**（273 − 9 = ShellC 专属用例）；build 通过。
- 真实浏览器（dev server，Electron 离屏）：默认加载与 `?shell=c` 均渲染
  `[data-testid="app-shell"]`（classic），`.shell-c` / `.shell-switcher` 均不存在，
  `?shell=c` 参数已失效无害。
