# 0029 · 主从视图 + 状态分组列表 + Playnite 式信息设计 + 深色主题（第4套 token）

日期：2026-08-08
状态：已接受

## 一、主从视图交互（Master-Detail，优先级最高）

**交互设计**：在资料库新增第三种浏览模式「分组列表」（☰，与网格 ▦ / 书架 ▤ 三选一，
localStorage 记忆 `tsumugi-lib-view`）。该模式**天然内嵌主从视图**：

- 左侧 = 状态分组紧凑列表（主），右侧 = 详情面板（从），**同屏显示**；
- 点击左侧任意条目，右侧详情**立即更新**（`fetchItemDetail` 按需拉取，不跳转、
  不弹层）；未选择时右侧显示占位提示；
- **复用 ADR 0028 的外壳**：主内容区（`flex-1 min-h-0 overflow-y-auto`）内部再分
  左右两栏，**左列表与右详情各自独立滚动**（各 `flex-1 min-h-0 overflow-y-auto`），
  不引入整页滚动；库头部 shrink-0 固定。
- 交互链路最短化：`点击列表行 → setDetailBrowseId → 右栏 useEffect 拉详情 → 渲染`。

## 二、状态分组列表（第三种浏览模式）

- 分组字段 = Review 的追番状态（想看/在看/看完/搁置/弃坑）+ **未收藏**（无书评状态）；
- 状态映射来源：前端 `fetchAllReviews()`（`GET /reviews`，时间倒序，首见即最新），
  构建 `item_id → status`，无需改后端；
- 每组：标题 + **数量角标** + 可**折叠/展开**（▾/▸，useState Set）；只显示有内容的组；
- 行 = 类型/来源图标 + 标题（选中高亮 accent 边框）；
- 视图切换入口与现有网格/书架一致（同一胶囊切换器），沿用 localStorage 记忆。

## 三、Playnite 式信息设计（结构性排版，四套主题统一生效）

新增共享组件 `components/ui.jsx`，复用点：

- **`InfoTable`（属性表格）**：label **右对齐** / value **左对齐**，行间细分隔线
  （首行无），走 token 配色。配合 `itemInfoRows(detail)` 从
  `raw_metadata.detail.metadata` 提炼"基本信息"行（数据源/原名/日期/发行日期/平台/
  开发商/大众评分/我的评分/投票数/卷数/集数/评分排名/页面信息）。
  应用到：**主从详情面板**、**ReviewStudio Overview**、**ItemDetailModal**。
- **`TagCapsule`（标签胶囊统一化）**：单一圆角矩形样式（`--tag-bg`/`--tag-text`
  = accent 系微弱变色，不随机上色），替换原先散落各处的
  `accent-soft/accent` 与 `tag-bg/tag-text` 两套标签样式 → 全站统一。
  应用到：主从详情面板、Overview、ItemDetailModal、分组列表行。

## 四、深色主题（第4套，token 兼容红线）

**遵守 ADR 0020**：只新增 `html[data-theme="dark"]` 色彩变量，间距/圆角/阴影/密度
token 一律复用 `:root`，不引入任何独立视觉规则。

配色原则（学习 Playnite"深色克制不灰/不过曝"，**不照抄具体色值**）：背景取克制深蓝灰
（#0e1116），面板略亮一档（#151a22），边框细分隔（#252d39）；文字高对比
（#e3eaf2 / 次级 #93a1b5 约 7:1）；强调色取**中亮蓝**（#4a9eff）保证深底对比，
不刺眼。tag/input/rail/card 各 token 一并深色化。

**强调色自定义兼容**：`themes.js` 的 `applyAccentHue` 增加深色分支——深色下
`--accent` 用中亮明度（≈68%）、`--accent-hover` 更亮（≈78%）、`--accent-soft` 用
**深色染**（≈13% 明度，深蓝灰 chip）而非浅色的近白（96%）。色相微调/密度/圆角
自定义范围与其它三套完全一致，同一套 `applyTheme` 管线。

## 五、明确不做

- 深色主题不做成脱离 token 体系的"特殊风格"（红线）；
- 不改变 Connector/RAG/插件等后端逻辑（本轮仅前端 + 复用既有 `/reviews`）；
- 不做 Playnite 游戏启动器等完整功能对标，只借鉴视觉与信息设计。

## 六、测试与实测

- **vitest 103 passed**（+11：主从视图点击切换详情、切换条目、分组列表折叠/展开与
  数量角标、InfoTable 对齐/分隔线、itemInfoRows 提取、TagCapsule、深色主题
  data-theme 与深色强调派生、与浅色主题对比；并更新原 themes.test 为四套断言）；
  build 通过。
- **实测（真实 App + headless Chrome，四主题 CDP 截图）**：
  - 主从视图：点击左侧分组列表条目（钢之炼金术师）→ 右侧详情 **h2 即时更新**为该
    条目标题，出现"基本信息"属性表格与标签胶囊；左列表/右详情 `overflow-y-auto`
    各自独立滚动；
  - 状态分组：真实库显示 `▾想看3 ▾看完4 ▾未收藏6`（数量角标），点击折叠
    `未收藏` 组 **6→0**（▾→▸），再点恢复；
  - 四套主题（default/mint/sakura/dark）各渲染 1280×800 PNG：`body` 背景色分别
    `rgb(250,250,250)/rgb(244,250,247)/rgb(253,246,247)/rgb(14,17,22)`，深色主题
    token 正确生效；InfoTable/胶囊/分组列表/主从详情在四主题下均正常。
