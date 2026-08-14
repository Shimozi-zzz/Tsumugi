# 0090 · Phase 10-1-A-4：Bangumi 导入后第一条记录引导

日期：2026-08-12
状态：已接受
基准：Phase 10-1-A-0 审计（Experience Loop 断点④：批量导入完成后无下一步建议）、
Phase 10-1-A-3（浏览面 § 经历标记）、8-3-A settings-action

## 一、决策

Bangumi 批量导入完成后增加 quiet next step：「去记录第一条回忆」。导入 job 仅含计数
（无 item_id 列表）→ 按任务回退方案**导向 Library**（grid）并显示 quiet 文案
「选择一部作品，写下你的第一次记录（§ 标记 = 已有记录）」。导入逻辑/去重/进度/错误/Memory
数据模型全冻结。

## 二、做法

- **BangumiPanel.jsx**：新增 `onRecord` prop；`job.state === "done"` 时在进度摘要下方渲染
  完成态卡（`导入完成，共 N 部作品加入书库（跳过重复 X · 失败 Y）`）+ `.settings-action`
  按钮「去记录第一条回忆」→ `onRecord(job.imported)`。
- **DesktopView.jsx**：`onRecord` → `setSection("library"); setLibView("grid"); setLibRecordHint(n)`；
  Library 书架范围行上方渲染 hairline + radius-control 的 quiet 提示行 + 收起按钮。
- 视觉：quiet text / mono / hairline / radius-control；无 CTA/accent-filled/白字/渐变/glow。

## 三、验证

- vitest **292 passed**（289 + 3：BangumiPanel 完成态显示入口并回调 imported=7、未导入不显示；
  DesktopView 集成——导入完成→点击→书库提示→收起 全链路）；build 通过。
- 真实浏览器：默认书库无提示（回归）、Bangumi 面板正常、1920/1440/1024/768/390
  `hOverflow=false`。真实 Bangumi OAuth 导入无法在离线环境执行（需真实账号），完成态全链路
  由集成测试验证。截图 `mem101a4_1920/1440/1024/768/390.png`。
