# 0028 · 修复左侧导航栏跟随内容滚动：改为标准应用外壳（app shell）布局

日期：2026-08-08
状态：已接受

## 一、Bug 根因（具体是哪个布局层级的 CSS 问题）

用户反馈滚动主内容网格时，左侧导航栏（图标条 + 资料库侧栏）跟着一起往上滚消失，
只剩折叠箭头。根因是**整个应用不是高度受约束的 app shell，而是"整页共用一个滚动
容器"**：

1. `App.jsx` 的 `.app-root` 是 `min-h-screen`（**不是** `height: 100vh`）；
2. `DesktopView` 根元素 `.desktop-view` 是 `minHeight: calc(100vh - 60px)`
   （**不是**固定 `height`）；
3. 结果：只要主内容（网格）比视口高，`.app-root` / `.desktop-view` 就随内容
   **不断长高**，于是 `body`（整个文档）成为实际滚动容器，把顶栏、导航、侧栏、
   主内容**一起**滚走；
4. 主内容区的 `overflow-y-auto`（原代码已有）**从未生效**——flex 子项默认
   `min-height: auto`，父级又无限长高，子项永远不会"溢出"自身，内滚动无从触发。

（顶栏当时用的是 `position: sticky`，理论上页面滚动时能钉在顶部；但 sticky 依赖
最近的滚动祖先，且与"整页滚动"的观感耦合，实测中顶栏也会跟着滚走——说明整页
滚动才是主问题，sticky 只是不牢靠的补丁。）

## 二、修复方案：标准应用外壳

```
┌──────────────────────────────────┐
│ header  顶栏（固定，shrink-0）      │  ← .app-root: h-screen flex flex-col
├──────┬───────────────────────────┤     overflow-hidden（视口高固定，整页不滚）
│ nav  │  main-content              │
│ 图标  │  .flex-1 min-h-0          │  ← 唯一的滚动容器 overflow-y-auto
│ 条    │  overflow-y-auto          │
│      │  （网格/书架/问答/角色墙/…）  │
│ aside│                           │  ← 侧栏内部 flex-1 min-h-0 overflow-y-auto
│ 资料库│                           │    （标签很多时侧栏自己内部滚）
│ 面板  │                           │
└──────┴───────────────────────────┘
```

具体改动：
- `App.jsx`：`.app-root` `min-h-screen` → `h-screen flex flex-col overflow-hidden`；
  顶栏去掉 `position: sticky`（外壳固定后天然钉顶），加 `shrink-0`；
- `DesktopView.jsx` 根：`minHeight: calc(100vh - 60px)` → `flex-1 min-h-0
  overflow-hidden`（填满顶栏以下的剩余高度，外壳不外溢）；
- **主内容区**：`flex-1 overflow-y-auto` → `flex-1 min-h-0 overflow-y-auto`
  ——加 `min-h-0` 是关键：取消 flex 子项默认的 `min-height: auto`，让它能被压到
  容器高度内、从而真正触发内部滚动；
- **图标导航**可排序区、**侧栏**内容滚动区：补 `min-h-0`（同样为内部滚动生效）；
- 侧栏容器/导航本就是 `.desktop-view` 的直接子级（平级），与主内容**不是父子**，
  滚动主内容在结构上不可能移动它们。

**波及范围（一并修复）**：资料库网格 / 书架 / 问答 / 角色墙 / 分析 / 设置全部渲染在
同一个主内容滚动容器内 → 一处 shell 修复覆盖所有视图；书评工作室是 `fixed inset-0`
独立浮层（自带滚动），不受影响。

**顶栏是否固定（决策）**：固定。符合管理类工具标准做法（顶部标题栏 + 侧边栏固定，
只有主内容区滚动）；外壳固定后顶栏天然固定，不再依赖 sticky。

## 三、已知边界

- 文字涂鸦层（absolute 定位在 `.desktop-view` 内）现在会被外壳 `overflow-hidden`
  裁剪：若用户把文字拖到首屏之外的绝对坐标会不可见（原本靠整页滚动可达）。这是
  装饰性功能的边界情况，本轮不处理，记入已知项。

## 四、测试与实测

- **vitest 92 passed**（+4 新增 `layout.test.jsx`）：
  1. 左侧导航/侧栏是主内容滚动容器的**兄弟节点**（结构证明滚动不可能带走它们）；
  2. shell 固定高度不外溢、主内容有独立滚动容器、侧栏有自己的内部滚动；
  3. 模拟主内容滚动（scrollTop=400）：导航/侧栏 bounding rect 不变；
  4. App 壳：`app-root` h-screen flex-col overflow-hidden、顶栏 shrink-0 且与
     工作区平级。
  build 通过。
- **实测（真实 App + headless Chrome，CDP 驱动）**：
  - 资料库网格：主内容 scrollHeight 4338 > 容器 747，滚动 800px 后
    `body.scrollY=0`（整页不滚）、`body.scrollHeight=innerHeight`（无整页外溢）、
    顶栏 top=0、导航/侧栏 top=53 **滚动前后完全不变**；nav/aside 不在主内容
    容器内（`main.contains(nav)=false`）；
  - 书架视图、角色墙视图：滚动主内容后同样 `body.scrollY=0`、导航/侧栏位置零变化
    （角色墙 scrollHeight>clientHeight 可滚动，书架内容未超高则无需滚动）；
  - 滚动前/后各截取 1280×800 PNG（`layout_before.png` / `layout_after.png`），
    可直观确认侧栏在滚动后仍固定可见、无空白区域。
