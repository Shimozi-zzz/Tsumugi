# 0096 · Phase 10-1-B-7：Metadata Rerank（统一 score 构造层）

日期：2026-08-12
状态：已接受
基准：B-3（intent routing）、B-5（occurred_at/emotion/milestone metadata）、B-6（temporal
signal，+0.15/−0.05）

## 一、决策

把 retrieval 的 score 构造重构为**独立、可测试的内部层** `_compute_retrieval_score`，
使最终 score 概念上 = base(semantic × source_weight) + temporal adjustment；仅启用
occurred_at temporal signal。不改任何数值/权重/池/cap/API/schema/UI，行为与 B-3/B-6
完全一致（真实数据 A/B 7/7 OLD==NEW）。

## 二、Rerank 模型（app/retrieval.py）

- **`_compute_retrieval_score(semantic_score, source_type, occurred_at, temporal_range)`**
  → `(final_score, temporal_adj)`：
  - `base = semantic × _source_weight`（memory/review/note=1.0、external=0.4，数值不动）；
  - temporal adjustment：仅当提供 `temporal_range` 且 source 为 personal（memory/review/note）
    时——within `+TEMPORAL_BONUS(0.15)` / outside `-TEMPORAL_PENALTY(0.05)` / occurred_at
    缺失或非法 `0`；external 不加不减；
  - 未来可在此层安全加入 emotion/milestone signal（本阶段不启用）。
- **Pipeline**：candidate → source filter/fallback → `_compute_retrieval_score`（base +
  temporal）→ content dedup → sort → per-item cap → top_k（rerank 在 dedup/cap 之前）。
- temporal_range 仅 `intent.temporal` 且有明确边界时计算（模糊词→None→不加不减）；
  普通/recommendation 问题 → None（零回归）。

## 三、验证

- 后端 pytest **458 passed**（452 + 6：base 保持、temporal hit/miss/unknown/非法、external
  无时间加分、语义主导、per-item cap 前 rerank、普通 query 零回归）；cov 85.87% ≥70%。
- 前端 vitest **296 passed**；build 通过。
- 真实数据（7 查询 A/B）：**7/7 OLD==NEW**（重构零行为变化）；真实库历史向量仍缺
  occurred_at → 时间信号对旧数据无效果，代码路径与兼容性已验证，真实召回质量提升无法证明
  （需新写入记忆产生 occurred_at 后生效）。
