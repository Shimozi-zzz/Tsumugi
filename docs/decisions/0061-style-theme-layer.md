# 0061 · 大风格主题层：编目抽屉·索书卡注册为首项（设置可切换）

日期：2026-08-11
状态：已接受
说明：将「编目抽屉·索书卡」（ADR 0054/0056/0060 索书卡正式形态）提升为**大风格主题**
（视觉语言层）注册项，放入「设置 → 外观」，为后续与其它大风格主题切换建立机制。

## 一、概念分层（与 ADR 0056 "版式与配色分离"对齐）

- **色彩主题（THEMES）**：只改色彩变量（现仅 default 编目抽屉纸感色板，ADR 0059）。
- **大风格主题（STYLE_THEMES）**：整体视觉语言——版式/材质/信息呈现，经
  `html[data-style-theme]` 作用域切换；首项为 `catalog-drawer`「编目抽屉·索书卡」。

## 二、实现

- `themes.js`：新增 `STYLE_THEMES`（首项 `{key:"catalog-drawer", label:"编目抽屉·索书卡",
  description:"真实档案卡：暖纸底 + 档卡横线 + 密集元数据行"}`）、`loadStyleTheme()`
  （无持久化/未知值回退首项）、`applyStyleTheme(key)`（写 `data-style-theme` + 持久化
  `tsumugi-style-theme`）。
- `App.jsx`：`styleTheme` 状态 + effect 应用 + 下发 `styleTheme/setStyleTheme`。
- `DesktopView.jsx`：设置「外观」新增「大风格主题」组（位于色彩主题之上），选中高亮，
  与其它主题共用选择器样式；现只有一项，机制已就绪。
- `index.css`：索书卡卡片样式（`.archive-card*`/`.catalog-no`/`.archive-ph*`）**正式收进
  `html[data-style-theme="catalog-drawer"]` 作用域**——不再是无作用域全局基础样式；其它
  大风格主题注册后以各自作用域覆盖。`main.jsx` 在首屏渲染前同步 `applyStyleTheme(...)`
  设置 `data-style-theme`，避免作用域未命中的首帧闪样。

## 三、测试与实测

- vitest **233 passed**（+3：STYLE_THEMES 注册 + applyStyleTheme 持久化与 data 属性、
  loadStyleTheme 回退、索书卡样式作用域断言——含无裸 `.archive-card` 规则）。build 通过。
