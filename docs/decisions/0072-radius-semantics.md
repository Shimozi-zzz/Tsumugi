# 0072 · Phase 2-5：圆角语义迁移（六级 Radius System）

日期：2026-08-11
状态：已接受
基准：ADR 0066（夜书房 token）+ Phase 2 命题（"纸、卡、封面、控件、标签、浮层各有正确物理感"）

## 一、六级圆角语义 Token（index.css :root 新增）

| Token | 值 | 语义 |
|---|---|---|
| `--radius-surface` | 4px | 页面/纸面，最克制近直角 |
| `--radius-card` | 6px | 独立内容对象（ArchiveCard） |
| `--radius-cover` | 4px | 封面，极轻微 |
| `--radius-control` | 8px | 输入框/按钮/选择器，温和不胶囊化 |
| `--radius-chip` | 999px | 标签/筛选条件，胶囊 |
| `--radius-floating` | 14px | 命令面板/弹层，最大但克制 |

数值沿用既有语言（4/6/4/8/999/14），仅为"为什么不同圆角"建立语义与单一来源。

## 二、迁移

- **Card/Cover**：ArchiveCard 卡面 → `--radius-card`（6px）、封面 → `--radius-cover`（4px），
  数值不变（无视觉回归）。
- **Control**：Library 搜索框（去胶囊化 8px）、视图切换组/按钮、批量选择按钮；
  侧栏分组/标签数量样式此前已降权。
- **Surface**：Library 主从视图两个面板 → `--radius-surface`（4px）。
- **Floating**：CommandPalette、MemoryReviewModal、ItemDetailModal、ShareCardModal 容器、
  Bookshelf 抽书预览 → `--radius-floating`（14px）。
- **Chip**：类型/筛选标签保持胶囊（999px，本就符合 Chip 语义）。

## 三、保留的历史圆角（遗留，原因）

- DesktopView 余下 rounded-2xl：检索台答案卡/历史浮层/设置 desk-askbar 卡/设置 tab/
  批量栏/导入·分组浮层——属 ask/settings/utility 区，非 Library 范围，留待各自页面阶段。
- CharacterWall / VoiceGraphView / InspectorPanel / YearlySummary / ProviderSettings /
  ShareCard 内层：非 Library 页面（本阶段禁入重设计）。
- 大量 rounded-xl/lg 在 ReviewStudio / ReviewPanel / ItemDetailPanel / BangumiPanel 等
  （rounded-lg 数值 8px = control，语义已覆盖；xl=12px 留待对应页面）。

## 四、验证

- vitest **248 passed**；build 通过。
- 真实浏览器：card 6px / cover 4px / search 8px / viewGroup 8px / batch 8px /
  chip≈999px / palette 14px；1920/1440/390 无横向溢出。
- 截图：radius25_1920/1440/390.png、radius25_grid1920.png。
