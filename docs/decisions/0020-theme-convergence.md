# 0020 · 主题体系收敛：三套克制主题 + 有约束的自定义框架

日期：2026-08-06
状态：已接受

## 背景与诊断

历次主题迭代（春樱/夏空/夜紫/玻璃拟态等）反复"换风格重来"，导致视觉语言
不统一、装饰元素过多（渐变背景、多层光晕、大范围磨砂模糊）显得"AI 生成感"
重。本轮不是加新主题，而是**收敛**：

- 过多装饰元素喧宾夺主；
- 卡片留白偏大、信息密度低，不像"图书馆/管理工具"；
- 间距/圆角/阴影节奏历次不一致，缺少统一设计 token。

## 一、三套主题 + 共享设计 token（核心约束）

### 共享 token（只在 `:root` 定义一次，主题不覆盖）
```
间距    --space-1..6        (4/8/12/16/24/32px)
圆角    --radius-sm/md/lg/xl  (8/12/16/20px)；--radius-lg 为主表面圆角
阴影    --shadow-sm/md/lg     (克制：分隔用边框，阴影仅用于浮起/浮层)
密度    --d-card-gap/pad/title/grid-min/font
        comfortable 默认；html[data-density="compact"] 覆盖为紧凑档
```
**只有 `--radius-lg` 可被自定义 inline 覆盖**，主题块不改布局节奏。

### 三套主题（只改色彩变量）
1. **经典白（default，默认）**：白/近白背景 `#fafafa`、白面板、细边框
   `#e8e8e8`、高对比文字、单一强调色蓝 `#2563eb`。最克制。
2. **薄荷 × 浅蓝（mint，"清醒"）**：薄荷绿强调 `#10b981`，次级信息用浅蓝
   （`--tag-text:#0369a1`、`--text-secondary` 偏蓝灰）——分区/状态区分而非
   渐变堆叠。
3. **樱花粉（sakura，ACG 向）**：淡粉底 `#fdf6f7` + 粉强调 `#ec4899`，
   保持"零生硬灰块"但避免少女心堆砌，遵循同一密度/间距规则。

### 视觉收敛
- 移除：per-theme body 渐变、desk-ambient 多层光晕、大范围 `backdrop-filter`
  磨砂、玻璃拟态覆盖、`bg-custom-layer` 背景图。
- 主表面统一：`border 1px var(--panel-border)` + `--shadow-sm`，hover 才
  `--shadow-md` + accent 描边（`.desk-card`/`.desk-askbar`/`.desk-searchbar`）。
- 主题切换只影响色板，布局/密度/圆角节奏全局一致。

## 二、有约束的自定义框架（不做自由取色/背景上传）

- **强调色色相**：在基准 accent 上 ±20° 微调（`ACCENT_HUE_RANGE`），运行时
  用 `hexToHsl` 旋转写 inline `--accent/--accent-hover/--accent-soft`；
  不提供完全自由的颜色选择器。
- **信息密度**：紧凑/舒适两档（`data-density` → `--d-*`），影响卡片间距、
  内边距、标题字号、网格最小列宽。
- **圆角大小**：12~24px（`RADIUS_RANGE`），inline 覆盖 `--radius-lg`，不提供
  直角/超大圆角极端。
- **移除背景图上传**：任务明确"背景图片上传等无约束自定义与调性不符"，
  作为旧迭代遗留一并移除（`bg`/`updateBg`/背景面板/bg-custom-layer）。
  文字涂鸦保留（任务未提及，且非主题装饰层）。

## 三、清理旧主题（真移除，非废弃）

- themes.js：仅保留 default/mint/sakura 三套；删除 spring/summer/
  violet-obsidian 及"备选"心智。
- index.css：删除全部旧主题色块与 per-theme 装饰覆盖。
- 组件：移除全部 `backdropFilter` 磨砂（19 处 → 0），主表面改走共享 token。
- 死代码确认（构建产物 grep）：`data-theme=summer/violet-obsidian/spring`、
  `desk-ambient`、`bg-custom-layer`、`glass-radius` 全部不存在；
  `data-theme=mint/sakura`、`--radius-lg`、`--d-card-gap` 存在。

## 四、测试与实测

- **vitest 53 passed**（themes.test 重写 + 自定义用例：data-theme/density、
  --radius-lg 钳制、accent 色相写 inline、自定义持久化 roundtrip；
  desktop-view/bookshelf props 更新）。
- pytest **266 passed**（无后端改动）；`npm run build` 通过。
- **实测（headless Edge，真实 index.css 提取的主题变量渲染 900×560）**：
  经典白（9KB，扁平克制）/ 薄荷（105KB）/ 樱花（65KB）三张截图，均为
  细边框 + 克制阴影、无光晕磨砂；另生成"default + 强调色+12° + 紧凑 +
  圆角20px"自定义预览截图，确认自定义层真实生效。
