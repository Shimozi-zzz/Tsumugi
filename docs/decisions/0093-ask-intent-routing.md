# 0093 · Phase 10-1-B-3：Ask 个人问题意图路由

日期：2026-08-12
状态：已接受
基准：Phase 10-1-B-2 审计（P2-2：纯语义检索对个人/时间/推荐型问题召回弱）、ADR 0025

## 一、决策

为 Ask 增加**轻量确定性意图识别**（不引入 LLM），按问题类型选择检索策略——只优化召回，
不改数据/向量/权重/API/UI/prompt。`_source_weight` 数值冻结（memory/review/note=1.0，
external=0.4）。

## 二、做法（app/retrieval.py）

- **`detect_query_intent(query)`**：关键词规则 → `QueryIntent{personal, temporal, recommendation}`。
  personal（我的/我喜欢/我想/我和/回忆/记录/评价/感想/看完/看了/喜欢…）、temporal（去年/
  以前/最近/当时/前年…）、recommendation（推荐/想重温/想看/类似/哪些作品/值得…）。
- **策略选择（_retrieve）**：
  - personal 或 temporal 且未显式指定 source_types → **个人来源优先**：`personal = [memory,
    review, note]`；个人内容 ≥ top_k 时**排除外部百科**；个人不足时 **external 兜底补位**
    （仍 0.4 加权排后）——避免百科抢占个人问题；
  - recommendation 或 temporal → **候选池扩大** `n_results = max(n_results, 80)`（原 40），
    提升多作品覆盖；最终上下文仍受 top_k / 去重 / prompt 预算约束；
  - 普通问题：行为不变（原池 + 混合排序）。
- 显式 `source_types` 传入时仍然优先（硬过滤），意图仅在未指定时生效。API 签名/响应不变。

## 三、验证

- 后端 pytest：**438 passed**（cov 85.69%；test_retrieval 23，含 +10：意图识别 4 例、个人
  优先排除外部/外部兜底/候选池扩大/普通不变 5 例 + 回归）；前端 vitest **296 passed**。
- 回归：普通问题（test_plain_query_unchanged）行为不变；`build_context_prompt` / source label
  未动；schema/API/UI/prompt 零改动。

## 四、验收

- 个人问题不再纯靠语义偶然命中（个人来源优先 + 外部兜底）✓
- Memory/Review 在个人问题中召回概率提升（来源过滤优先）✓
- 推荐/时间问题获得更大候选池（40→80）✓
- 普通知识问题行为保持 ✓；无 schema/API/UI 变化 ✓
