# 0074 · Work Detail 阶段约束（用户钦定限制，逐条记录）

日期：2026-08-11
状态：已接受（约束记录）
说明：进入 Work Detail 重设计阶段前的**用户钦定限制清单**，逐条原文记录，作为该阶段
绑定约束；任何实现不得违反。未开始 Work Detail，仅登记。

## 限制清单

1. 禁止修改后端 API
2. 禁止修改数据模型
3. 禁止 Item → Work 重命名
4. 禁止新增 Experience / Timeline 实体
5. 禁止修改 Collection 状态语义
6. 禁止重新设计 Review Studio
7. 禁止重新设计 MemoryReviewModal
8. 禁止修改 MemoryTypeTag 的既有语义
9. 禁止新增 Dashboard/统计卡
10. 禁止为了视觉效果增加虚假数据
11. 禁止顺手修改 Library
12. 禁止顺手修改 Gallery / Timeline
13. Classic 与 ShellC 必须共享同一 Work Detail 设计语言
14. 每个小步必须 vitest → build → 浏览器验证 → 报告 → 停止
15. 未经下一步确认不得继续

## 说明

- 第 13 条：Work Detail 将是两外壳共用的同一组件/设计语言（预计以共享 `ItemDetailPanel`
  为基底做视觉重设计，Classic 与 ShellC 复用同一呈现）。
- 第 14/15 条：沿袭 Phase 2 的小步纪律（改→测→build→浏览器→报告→停，逐次确认）。
- 本文只登记约束，不包含任何实现。
