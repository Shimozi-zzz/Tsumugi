# 0092 · Phase 10-1-B-1：Ask 个人语境提示词对齐

日期：2026-08-12
状态：已接受
基准：Phase 10-1-B-0 审计（P2：系统提示未把「记忆」列为个人来源、个人相关问题优先指令缺失；
Memory/Review 已入 context 但角色未明确）

## 一、决策

只改 `app/rag.py` 的 `SYSTEM_PROMPT_TEMPLATE`（+ 对应 pytest）：在不改检索架构/向量/权重/
API/UI/schema 的前提下，把个人来源统一为 **我的记忆 / 我的书评 / 我的笔记**，并指导模型：
个人相关问题（为什么喜欢/与我的关系/我的经历/去年/想重温/推荐我）优先个人记录（记忆→书评→
笔记），无记录时明说"没有找到你关于这一点的个人记录"不臆造；回答区分「你的记录中……」与
「资料显示……」。现有 source label（build_context_prompt）与 `_source_weight` 数值零改动。

## 二、做法

- `SYSTEM_PROMPT_TEMPLATE`：来源定义段加入「我的记忆」并统一为「用户自己的记录（个人经历）」；
  新增第 3 条个人问题优先级规则（含 6 类语义关键词 + 优先级 + 无记录回退）；新增第 4 条来源
  区分措辞（你的记录中/资料显示）。
- `tests/test_rag.py`：+5 断言（个人来源定义、优先级关键词+顺序+无记录回退、来源区分措辞、
  build_context_prompt 的 记忆/书评/百科 标签不回归）。

## 三、验证

- 后端 pytest：**430 passed**（cov 85.63% ≥70%；test_rag 17 passed，含新增 5 例）。
- 前端 vitest **296 passed**；`npm run build` 通过（UI/API 零改动，无回归）。
- 数据流无变化：Memory/Review 继续经 `retrieve_chunks`（权重 1.0）进入 context；external 权重
  0.4 不变；来源标签不变；Ask UI 不变。
