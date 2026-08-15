# 0098 · Phase 10-1-B-9：source-aware per-item cap（个人深度 2）

日期：2026-08-12
状态：已接受
基准：B-7（rerank 层）、B-8（emotion/milestone）、ADR 0025（来源）

## 一、决策

解决 `max_chunks_per_item=1` 导致的"同作品个人记录深度不足"：默认路径改为 **source-aware
cap**——personal/temporal intent 允许同作品最多 2 个**不同个人来源实体**（memory+review /
review+note），recommendation/neutral 保持 1（跨作品广度）；显式传入 `max_chunks_per_item`
时保持旧行为（不启用 entity 规则，兼容既有测试/调用）。

## 二、行为（app/retrieval.py）

- **实体身份**（`_passes_item_cap`）：memory 用 `memory_id`、review 用 `review_id`、note 用
  (item, note)、external 用 (item, external)；同一实体 ≤1 个 chunk；身份缺失（历史向量无
  memory_id/review_id）→ 按 (source_type, item) 保守合并，不跨源合并、不猜测同一性。
- **策略**：默认路径（未显式 cap）——personal/temporal → 同 item ≤2 个不同实体；
  recommendation/neutral → 同 item ≤1；显式 `max_chunks_per_item` → 每 item ≤cap（旧行为）。
- **Pipeline**：candidate → source filter/fallback → rerank → content dedup → sort →
  **entity-aware cap** → top_k（rerank score 优先）。
- external 不获得个人深度（不占 2 个槽位）；同一 review/memory 多 chunk 不会重复占位。

## 三、验证

- 后端 pytest **482 passed**（471 + 11：同 review/memory 多 chunk 只 1、memory+review /
  review+note 同作品共存、三实体最多 2、neutral/recommendation 同作品 1、recommendation
  广度保持 5、temporal+personal 共存、external 不占个人深度、legacy 缺身份不报错、显式 cap
  回归）；cov 86.05% ≥70%。
- 前端 vitest **296 passed**（全量一次并行 flaky 后重跑绿）；build 通过。
- 真实数据（4 personal + 3 recommendation + 2 temporal + 3 neutral A/B）：neutral 3/3 与
  recommendation 3/3 **零回归**（unique_works 保持 5）；temporal「最近我留下了哪些记录」
  **出现预期差异**——「RAG技术笔记」同作品 review+note 共存（same_work_multi 0→1、
  unique 5→4）；未出现单作品吞 top-k、同 review 重复、external 获个人深度、legacy 报错。
  真实库无 direct memory 向量 → memory+review 共存无法用真实数据证明，但 review+note
  （同一深度 2 机制）已在真实数据上证实。
