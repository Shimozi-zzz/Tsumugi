# 0037 · 封面氛围色延伸到网格卡片 hover 与书架书脊高光

日期：2026-08-08
状态：已接受

## 一、背景与思路

ADR 0034 的封面取色氛围已在主从详情面板实现（前端 Canvas + 按 URL 缓存直方图主导
色 + `--ambient-alpha` 克制参数 + 过灰/黑/白降级）。本轮把它**延伸到网格卡片 hover
与书架书脊 hover**：完全复用 `ambient.js` 的 `extractPalette`（含缓存），不重新实现
取色。书脊主体配色仍按 ADR 0019 标签哈希规则，取色高光只是 hover 的**额外点缀层**。

## 二、实现

### 组件 `components/CoverAmbient.jsx`
- 包裹卡片/书脊，`onMouseEnter/Leave` 驱动 hover 状态；**hover 才触发取色**
  （懒加载，页面加载不为所有可见卡片预计算），命中 `extractPalette` 缓存后重复
  hover 不重算；
- 渲染一个绝对定位的 `box-shadow` 光晕层（`inset:0`、同圆角、`pointer-events:none`、
  z 在内容之上但可穿透），hover 时浮现、离开淡出，`transition: box-shadow 0.3s`。

### hover 强度参数（明显弱于详情面板）
- 光晕 alpha = `--ambient-alpha × alphaFactor`：卡片 `alphaFactor=0.6`（浅色 ≈0.10、
  深色 ≈0.18），书脊 `0.7`（浅色 ≈0.11）——远低于详情面板的 0.16/0.30；
- 光晕半径：卡片 `0 0 18px 2px`，书脊 `0 0 12px 1px`（更细的边沿高光）；
- **降级**：无封面 / 取色失败 → `color-mix(in srgb, var(--accent) 16%, transparent)`
  （主题 accent 高光，保留 hover 反馈，不因取色失败而无反馈）。

### 书脊主色与 hover 高光的层级关系
- 书脊主体 `backgroundColor` 仍由 `spineColor(spineSeed(it))`（标签哈希）决定——**不
  被取色高光覆盖/替换**；CoverAmbient 的光晕是独立一层 box-shadow 外发光，仅 hover
  时叠加，离开即消失。

### 顺带修正：卡片封面取色读不到本地缓存
- 排查发现网格 `cardCover` 此前**优先 remote image_url**，而详情面板/安利卡优先
  **本地缓存 file_path**——远程封面在浏览器里可能加载失败/CORS → 取色降级。已改为
  与详情面板一致：优先本地 `filePathToUrl(file_path)`（同源可靠），remote 兜底。

## 三、性能确认
- 取色只在**单张卡片/书脊 hover** 时触发，且 `extractPalette` 按 URL 缓存（模块级
  Map，命中直接返回同一 Promise）；同屏大量卡片不会在加载时批量取色，无卡顿。
- 为可测试性把 `extractPalette` 拆为缓存包装 + `_computePalette`（实际 Canvas 计算，
  导出供测试验证缓存命中），并把 `extractPalette` 改为**非 async**（直接返回缓存
  Promise，不再每次调用包一层新 Promise，使"同一 URL 返回同一引用"可观察）。

## 四、测试与实测

- **vitest 156 passed**（+9：`ambient-cache.test.js` 缓存复用——同一 URL 返回同一
  Promise、只创建一次 canvas、不同 URL 各自计算、无 src 返回 null；`cover-ambient
  .test.jsx`——hover 懒触发取色 + 光晕用封面主色、离开恢复透明 + 0.3s 过渡、无封面
  /取色失败回退 accent 高光、书脊 hover 高光且**不覆盖标签哈希主色**、书脊无封面
  accent 降级）；build 通过。
- **实测（真实 App + headless Chrome CDP，真实数据）**：
  - 网格卡片 hover：魔法少女小圆 → `rgb(183,197,188)` a=0.094、另一个小圆条目 →
    `rgb(249,168,168)`（不同封面不同色调）、命运石之门系列 → `rgb(53,54,9)`——与
    ADR 0034 详情面板实测同封面色调**完全一致**；
  - 书架书脊 hover：小圆 → `rgb(183,197,188)` a=0.114（与卡片/详情同调），且书脊
    主体仍是标签哈希色；
  - 强度层级：卡片 0.094 < 书脊 0.114 < 详情面板 0.16（均明显弱于详情）；
  - 截图 ambient_grid_hover.png / ambient_shelf_hover.png。
