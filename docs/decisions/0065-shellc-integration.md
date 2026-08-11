# 0065 · ShellC 整合既有功能：书库三视图 + 管理室真实化 + 命令面板

日期：2026-08-11
状态：已接受
基准：ADR 0064（ShellC 交互化）+ ADR 0049（书架）/0029（分组列表）/0031（命令面板）
/0038（备份）+ AGENT_UI.md（图书馆空间隐喻）

## 一、动机

ADR 0064 后 ShellC 各房间可交互，但仍是"轻量版"：书库只有网格一种浏览、管理室只有
外壳切换、无命令面板。用户要求**把已有功能结合并整合**进 ShellC，复用既有资产而非
另起一套。

## 二、变更（全部复用既有组件/API，后端零改动）

1. **书库三视图 + 筛选（ShellLibrary）**：
   - 浏览模式：网格（ArchiveCard+CoverAmbient）/ 书架（Bookshelf，ADR 0049）/ 分组列表
     （StatusGroupedList，ADR 0029，点行开详情弹层）；
   - 作品类型筛选 chips（work_type，有数据才显示）+ 库内搜索（标题/内容）；
   - 视图选择持久化 `tsumugi-shell-lib-view`。
2. **管理室真实化**：
   - 应用外壳切换（ADR 0064）；
   - **AI Provider**：复用 `ProviderSettings`（可选扩展，Core 无 AI 完整）；
   - **数据备份**：导出/导入 JSON（复用 exportBackup/importBackup/fetchImportStatus，
     ADR 0038，后台向量重建，导入完成 toast）。
3. **命令面板 Ctrl/Cmd+K**：
   - `CommandPalette` 支持 `commands` prop（直接用外部命令集，否则 buildCommands(ctx)）；
   - ShellC 作用域命令集：切换六个房间 + 切换主题（THEMES）+ 条目搜索（打开详情弹层）。
4. **ToastHost 移到外壳分支外**（两外壳共用，ShellC 内导出/导入等 toast 可正常显示）。

## 三、明确不做

- 不把完整检索台（联邦搜索+AI 流式+来源渲染）从 DesktopView 抽出（大重构，单独排期）；
- 不搬入批量操作/右键菜单/文字涂鸦等 DesktopView 深度绑定能力；
- 不改后端、不新增表/接口（全部复用 /items、/collections、/llm/*、/backup/*）。

## 四、测试与实测

- vitest：+3（书库三种浏览切换、管理室真实化三块、Ctrl+K 命令面板切房间）；全量
  **243 passed**。build 通过。
