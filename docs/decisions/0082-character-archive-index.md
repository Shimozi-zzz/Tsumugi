# 0082 · Phase 8-1-A：Character Archive 主列表档案化收敛

日期：2026-08-12
状态：已接受
基准：Phase 8-0 审计（CharacterWall = 混合状态 D：大圆角卡片墙 + pill/chip-card + 实心 accent）、ADR 0072（radius 语义）

## 一、决策

把 CharacterWall 主列表从「SaaS 人物卡片墙」收敛为「人物档案馆·档案索引墙」。
数据/API/交互全冻结：`fetchCharacters` / `onOpenWork` / `onOpenVoice` / 选中态 全保留。

## 二、做法

- **主列表 → 档案索引条目**（`.char-entry`）：外层 `--radius-card`（6px，原 borderRadius 16）、
  mono 编目行 `№ 001`（`.char-entry-no`）、serif 人名（`.char-entry-name`）、quiet mono
  metadata（`.char-entry-meta` 来源·部数 + `.char-entry-cv` 声优）——不再逐项 pill/chip；
  portrait 作为档案小像 `--radius-cover`（4px），不是卡片主视觉；无渐变/glow/实心 accent。
- **档案索引行**（`.char-index`）：mono `CHARACTER INDEX · N 位` + hairline。
- **选中详情**（`.char-detail`）：`rounded-2xl` 面板 → `--radius-card` 档案卡；声优 accent-soft
  pill → quiet mono 链接（hover accent-soft）；作品 rgba 白底 chip-card → hairline `--radius-card`
  档案行（小像 + 标题）。`收起`/`出自作品`/`声优（点名字看关系图谱）` 文案与行为不变。
- **hover/selected**：hover = `--surface-2` + hairline 加深；selected = accent hairline +
  accent-soft 外圈。全部 button 显式 `type="button"`（Tab/Enter/Space 原生激活）。
- **PageHeader「声优关系/刷新」**：位于 DesktopView（本轮严格范围外），未改——如实遗留。

## 三、验证

- vitest **275 passed**（274 + 1：档案索引条目结构断言——mono 编目/serif 人名/quiet meta/
  无 pill、详情声优为 quiet 链接）；build 通过。
- 真实浏览器（Electron 离屏 + 真实库 1605 位角色）：1920/1440/1024/768/390 全
  `hOverflow=false`；`.char-entry` radius **6px**（radius-card）、portrait **4px**（radius-cover）、
  人名 Georgia serif、编目 ui-monospace；char-archive 内 pills=0 / rounded-2xl=0 /
  accent-filled=0；点击条目开详情、作品行触发 onOpenWork、1605 个 button 全部
  `type="button"`（Tab/Enter/Space 语义保证）；截图 `char81_1920/1440/1024/768/390.png`。
