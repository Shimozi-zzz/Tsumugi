# 0064 · 非对称档案室交互化 + 外壳切换入设置

日期：2026-08-11
状态：已接受
基准：ADR 0057/0059（外壳收敛保留 classic + C）+ ADR 0061（设置分层）+ AGENT_UI.md
（检索台/书库/人物馆/关系厅/记忆回廊/管理室的空间隐喻）

## 一、动机

ShellC（C 非对称档案室）此前是"探索版"外壳：书库卡片 `onOpen={() => {}}` 点不动、
检索台命中不可点、回廊/人物馆/关系厅未接线、管理室是"探索版仅示意"占位；外壳切换
只有右下角浮动开关（探索期产物）。

## 二、变更

1. **ShellC 交互化（AppShells.jsx）**：
   - 书库：点 ArchiveCard → 打开**作品档案详情弹层**（`ItemDetailPanel` 自取数据，
     含外部世界 + 我的记录 + 时间轴），可关闭；
   - 检索台：作品/书评/记忆命中行改为可点击——作品开详情弹层，书评/记忆开
     `MemoryReviewModal`（复用现有只读弹层）；
   - 记忆回廊：`onOpenWork` 接线 → 点条目开详情弹层；
   - 人物馆/关系厅：`onOpenWork` / `onOpenVoice`（跳关系厅并聚焦）接线；
   - 管理室：不再是"探索版仅示意"，提供真实设置入口（应用外壳切换 + 提示数据管理
     在经典三栏管理室）。
2. **切换入口移入设置**：
   - 移除 DesktopView 右下角浮动 `ShellSwitcher`；
   - 经典三栏「设置 → 外观」新增「应用外壳」块（`ShellSwitcher`）；
   - ShellC「管理室」提供同一 `ShellSwitcher`（经 `shellValue/onShellChange` props）。
3. 后端零改动；沿用编目抽屉 token（ADR 0056）。

## 三、明确不做

- 不在 ShellC 复制经典三栏的全部设置（数据管理/导入导出仍走经典三栏管理室）；
- 不改数据模型、不新增后端接口（全部复用 /search/my、/memories、/items/{id}/detail、
  /items/{id}/memories、/items/{id}/reviews、/characters、/voice-relations）。

## 四、测试与实测

- vitest：+3（书库点卡开详情弹层可关闭、检索台命中可点开记忆弹层、管理室外壳切换
  回调）；全量 **240 passed**。build 通过。
