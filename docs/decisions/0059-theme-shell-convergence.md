# 0059 · 主题/外壳定案：仅默认主题 + 经典三栏 / 非对称档案室

日期：2026-08-10
状态：已接受
说明：用户定案——**主题颜色仅保留默认（编目抽屉纸感）**；**外壳保留「经典三栏」与
「C 非对称档案室」**两个。本轮将既有探索产物收敛为正式形态（非新增功能）。

## 一、主题收敛：仅默认

- `themes.js`：`THEMES` 仅剩 `[{ key: "default", label: "编目抽屉" }]`；
  `ACCENTS` 仅 default `#b25b36`；`DARK_THEMES` 清空（无深色主题，分支保留为将来扩展）。
- `index.css`：移除 `html[data-theme="mint"/"sakura"/"dark"]` 三块；默认 `:root`
  （编目抽屉纸感，ADR 0056）为唯一色板。
- 兼容：用户 localStorage 里若存有旧主题名，`loadTheme` 回退 default（优雅降级）；
  命令面板「主题」组仍存在，但只有一项「切换主题：编目抽屉」。
- 理由：收敛到唯一成熟配色（纸感 + 暖橙），减少维护面；多主题投入产出比低，后续若
  需要再按"版式与配色分离"扩一套。

## 二、外壳收敛：经典三栏 + C 非对称档案室

- 移除探索方向 A 卡片抽屉、B 书脊索引（组件 + 各自 CSS + 开关项）。
- `AppShells.jsx`：`SHELL_CONCEPTS` 仅 classic / c；`ShellC`（非对称档案室）保留为
  可选外壳；右下角浮动开关仅两项；`?shell=classic|c` 直达。
- `DesktopView`：外壳分支只判断 classic → 正常布局，否则渲染 `ShellC`。
- 理由：A/B 的结构主张经对比未被采纳；C（不同房间格局不同）与既有"图书馆空间"隐喻
  更契合，保留作为可选外壳。

## 三、测试与实测

- vitest **234 passed**（主题测试改单套断言 + 断言无 mint/sakura/dark 块；外壳测试仅
  ShellC + 2 项开关；命令面板主题组 1 项；master-detail 表面 token 断言适配纸感 :root；
  review-doc 主题渲染改默认）。build 通过。
- 实测见简报（默认主题 + ShellC 仍正常渲染）。
