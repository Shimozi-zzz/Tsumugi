# 0031 · 命令面板（Command Palette）：Ctrl/Cmd+K + 动作注册表

日期：2026-08-08
状态：已接受

## 一、与现有 `/` 聚焦搜索的关系（快捷键决策）

**决策：`Ctrl/Cmd+K` 从"聚焦问答搜索框"改为"呼出命令面板"；`/` 保留"聚焦问答搜索"。**

理由：
- `Ctrl+K` 是命令面板的事实行业标准（VS Code / GitHub / Figma / Obsidian 等），
  用户键入 Ctrl+K 的预期就是弹出一个启动器/命令面板；把它绑定到"聚焦搜索框"不符合
  肌肉记忆。改绑命令面板是"更符合惯例"，而不是发明新键位。
- `/` 与 `Ctrl+K` 用途不同：`/` 是问答区的**就地文本搜索**（RAG 提问），`Ctrl+K`
  是**启动器**（执行动作 / 跳转条目 / 切主题 / 按标签跳）。两者并存互不冲突，
  原 Ctrl+K 的"聚焦问答"能力没有丢失（`/` 仍在），只是换了更合适的键位。
- 原 `interactions.test.jsx` 中"Ctrl+K 聚焦问答搜索框"断言同步更新为"呼出命令面板"。

## 二、动作注册表设计（可扩展性）

集中在 `frontend/src/commands.js`：
- `buildCommands(ctx)` 返回全部命令（数组），每条命令含
  `{ id, group, title, keywords, icon, run }`；
- **分组**：`条目`（内容搜索，动态生成）/ `动作`（预定义）/ `主题`（四套，动态）/
  `标签`（动态）；`GROUP_ORDER` 定义展示顺序；
- **ctx 只依赖一组可执行回调**：`{ items, tags, openItem, openImport, section, ask,
  setTheme, openTag, shareCard, reviewStudio }`，由 DesktopView 绑定到真实状态；
- **后续扩展**：声优图谱 / 年度热力图等完成后，只需在 `buildCommands` 追加一条
  `{ group: "动作", title: "打开声优图谱", keywords: [...], run: () => ctx.xxx() }`，
  面板的过滤/分组/键盘导航逻辑零改动。
- `matchCommand`：查询串去空格小写后对 title/keywords 做**子串匹配**（模糊搜索），
  不引入 NLP。

## 三、命令面板组件（`components/CommandPalette.jsx`）

- `Ctrl/Cmd+K` 呼出（悬浮居中弹层，背景轻微遮罩 `rgba(8,10,18,0.45)`）；
- 输入实时过滤（`matchCommand`），**按类型分组展示**（分组标题复用 Overview 的
  "区段标签"排版：text-[11px] tracking-wider），空查询时只展示动作/主题/标签
  （条目量大，避免刷屏），有查询才展示匹配条目；
- **键盘**：↑/↓ 移动选择（扁平索引，hover 同步），Enter 执行并关闭，Esc 关闭；
- **无匹配空状态**："没有匹配的命令或资料。"
- **视觉遵守 token**：surface-1 面板 + panel-border + shadow-lg + accent 高亮选中，
  结果区 `max-h-[46vh] overflow-y-auto`（独立滚动，不引入页面滚动，ADR 0028）。

## 四、内容搜索 → 主从详情（最高频场景）

`条目` 命令 = 已收藏条目标题模糊匹配（paletteItems = items prop ∪ gridItems 去重），
选中回车 → `ctx.openItem(it)` → `setSection("library"); setLibView("list");
setDetailBrowseId(it.id)` → **主从视图右侧详情面板直接切换**（复用 ADR 0029）。

## 五、测试与实测

- **vitest 118 passed**（+12：注册表四组/主题四条/matchCommand 去空格匹配；面板
  过滤/键盘导航/内容搜索 openItem/主题切换 data-theme/空状态/执行后关闭；DesktopView
  集成 Ctrl+K 呼出+Esc 关闭、内容搜索跳转主从详情 h2；并更新原 interactions 的
  Ctrl+K 断言）；build 通过；pytest 358（无后端改动）。
- **实测（真实 App + headless Chrome CDP）**：
  - `Ctrl+K` 呼出命令面板（input placeholder "搜索资料…" 出现）；
  - **键盘导航**：输入"打开"后 `ArrowDown` → `Enter`，执行的是第二条"打开问答"，
    界面切到问答区（搜索框出现）、面板自动关闭；
  - **内容搜索跳转**：输入真实条目标题"钢之炼金术师" → `Enter` → 面板关闭，主从
    视图出现且右侧详情 `h2` = "钢之炼金术师 FULLMETAL ALCHEMIST"（复用主从详情）；
  - **主题切换动作**：输入"深夜深蓝" → `Enter` → `documentElement data-theme = dark`
    （深色主题即时切换）；
  - `Esc` 关闭面板；截图 `palette_jump.png`（跳转主从详情）/ `palette_dark.png`
    （深色主题）。
