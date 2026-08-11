# 0073 · Phase 2-6：Library Responsive 收口（Phase 2 收官）

日期：2026-08-11
状态：已接受
基准：ADR 0066-0072（夜书房 Design System / Library 各小步）+ Phase 2 命题（同一 Library
在 Desktop / Tablet / Mobile 保持同一设计语言、信息层级与交互能力）

## 一、全 7 viewport 审计（真实浏览器）

1920 / 1440 / 1024 / 768 / 430 / 390 / 375 全部 **hOverflow=false**；发现并修复三处真实问题：

1. **移动端单列巨卡**：网格 `minmax(190px,1fr)` 在 ≤560px 只剩 1 列 ~300-350px 巨卡
   → 新增 `@media (max-width:560px) { :root { --d-grid-min: 140px } }`：390→2 列 149px、
   375→2 列 141px、430→2 列 169px；Desktop（1920 7 列 / 1440 4 列）不变。
2. **移动端主从视图挤压**：原 `w-[300px]` 列表 + 详情并排，窄屏详情被压到近 0
   → 主从视图响应式：桌面（lg+）保持左右主从；窄屏列表全宽（`w-full lg:w-[300px]`、
   `flex-col lg:flex-row`、详情面板 `hidden lg:flex`）+ **全屏 Detail Scene**（复用
   `ItemDetailPanel` 与 `detailBrowseId`，`window.innerWidth<1024` 守卫 + CSS `lg:hidden`
   双保险，不新增第二套详情系统）。
3. **触控目标**：视图切换按钮 25px → 29px（`py-1.5`）。

## 二、保持不变（未重设计）

- 未改 ArchiveCard 核心 / Toolbar 核心 / 状态分区语义 / Radius 语义 / Shell / PageHeader /
  Bottom Navigation / 命令面板；未新增 Filter Drawer / Bottom Sheet / 新命令系统；
- 侧栏沿用 ≤768px 隐藏；底部导航沿用 64px 下边距；Motion 仅用既有 token；圆角沿用六级语义；
- 未改 API / 数据模型 / Collection 状态 / 业务逻辑。

## 三、验证

- vitest **248 passed**（主从视图用例：窄屏详情浮层用 JS 视口守卫避免 jsdom 无 CSS 时
  与右侧面板重复渲染）。build 通过。
- 真实浏览器 7 视口：gridCols 7/4/2/2/2/2/2、cardW 193/229/266/226/169/149/141、
  master-detail 窄屏首面板全宽、viewBtnH 29、hOverflow 全 false。
- 截图：resp26_1920.png / resp26_1024.png / resp26_390.png。
