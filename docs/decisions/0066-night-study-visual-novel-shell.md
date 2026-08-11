# 0066 · 夜书房 · Visual Novel Archive：Design Tokens + Application Shell（Phase 1）

日期：2026-08-11
状态：已接受
基准：docs/product-brief-v1.1.md + AGENT_UI.md（图书馆空间隐喻 / 反模板）+ ADR 0020
（token 框架）/0056（编目抽屉）/0059（外壳收敛）/0061（风格主题层）

## 一、视觉方向

**「夜书房 · Visual Novel Archive」**：纸与墨为骨、暖橙唯一主强调、作品氛围色只作
Scene Layer；克制、留白、日式出版物与视觉小说气质。UI 名称转为图书馆空间（馆内导览），
内部 section 键/路由/数据结构**一律不改名**。

## 二、Design Tokens（index.css :root 新增，全站唯一来源）

- **Typography 字阶**：`--fs-display/heading/subheading/title/body/caption/micro` +
  leading/tracking。
- **Spacing**：`--sp-1..12`（4px 基网格；旧 --space-* 并存，逐步收敛双轨）。
- **Border**：`--border-hairline(-accent)/dashed`。
- **Ink 层级**：`--ink-0/1/2`。
- **Scene Surface**：`--scene-surface`（氛围色只做 hero 层，保证正文对比度）。
- **Shadow**：`--shadow-float`。
- **Motion**：`--dur-enter 180ms / open 240ms / reveal 400ms` + `--ease-standard` +
  `--motion-enter/open/reveal`。
- **Focus**：`--focus-ring` + 全局 `:focus-visible`。
- **Reduced motion**：全局 `prefers-reduced-motion` 瞬时退化。

## 三、Application Shell（Desktop 经典外壳 → 馆内导览）

- **左侧导航**：`renderNavItem` 生成馆室项（serif 馆室名 + mono 编号），分组
  馆室 ROOMS（书库/记忆回廊/时光轴/人物档案）+ 工具 TOOLS（分析/声优图谱），
  检索台固定顶部、管理室固定底部；保留长按/拖拽排序。UI 房间→内部键映射
  `ROOM_META`（时光轴当前承载 summary 年度总结，全局轨迹后续阶段新建）。
- **顶栏**（主内容 sticky）：mono 面包屑（房间/英文）+ 全局检索入口 + Ctrl+K 命令入口
  + 移动端汉堡。
- **页面头**：共享 `PageHeader`（serif 房间名 + hairline + mono 路径），应用到
  书库/记忆回廊/人物档案/声优图谱/时光轴/分析/管理室；MemoryGallery 增 `showHeader`
  prop（classic 由 PageHeader 承接标题）。
- **命令面板**：视觉改为「索书卡式检索浮层」（纸卡 + serif 馆藏检索 + hairline +
  mono 提示），Ctrl+K 行为与命令系统不变。
- **响应式**：Desktop 完整馆内导览；Tablet（<1024px）导览收缩为抽屉（汉堡呼出）；
  Mobile（≤768px）底部房间导航 + 主内容下边距；`prefers-reduced-motion` 全局支持。

## 四、明确不做

- 不重命名内部 section 键/路由/数据结构；
- 不进入 Library / Work Detail / Composer / Gallery / Timeline 的正式重设计；
- 不改后端/数据库/模型/RAG/AI/Connector；
- 不新增功能（时光轴为 UI 呈现，年度总结仍是其 Phase-1 内容）。

## 五、测试与实测

- vitest **246 passed**（+3 馆内导览/顶栏/抽屉；旧导航 title 用例合理更新：图书馆→书库、
  记忆回廊断言改 GALLERY 页面头）。build 通过。
- 截图/视觉检查：见开发流程简报（Chrome CDP 截图核对）。
