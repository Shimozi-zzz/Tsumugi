# 0095 · Phase 10-1-B-6：Temporal Retrieval（occurred_at 时间信号）

日期：2026-08-12
状态：已接受
基准：Phase 10-1-B-4（P2-1：时间型问题无时间信号）、Phase 10-1-B-5（occurred_at metadata 就绪）、
Phase 10-1-B-3（intent routing + candidate pool）

## 一、决策

为 temporal intent 的个人问题启用 occurred_at 时间信号：`先判断 temporal intent → 解析明确
时间范围 → 对命中 occurred_at 的 personal chunk 加分、范围外减分 → 保留 personal/source
strategy → 最终排序`。仅 additive 微调（在 per-item cap 前生效），不做硬过滤、不做时间
metadata 检索、不修改 weight/top_k/cap/API/schema/UI。

## 二、时间信号设计（app/retrieval.py）

- **`_current_time()`**：可注入的当前时间 provider（production=系统时间；tests monkeypatch
  固定，避免随机器日期漂移）。
- **`_explicit_temporal_range(query, now)`**：仅对明确时间词返回 [start, end] 闭区间（naive）：
  前年/去年/今年=日历年；上个月=上月 1..月末；上周=ISO 周（周一）上一周；昨天=前一天；
  最近=固定 30 天窗口（项目无既有定义）。模糊词（以前/之前/那时候/当时）→ None（不虚构、
  不硬过滤）。
- **`_parse_occurred_at(value)`**：解析 B-5 的 ISO-8601（date/datetime、可含时区，统一 naive
  墙钟）；None/非法/缺失 → None，单条格式异常绝不导致 retrieval 失败。
- **策略**：`intent.temporal` 且有明确范围时，对 personal chunk（memory/review/note）——
  范围内 `+TEMPORAL_BONUS(0.15)`、范围外 `-TEMPORAL_PENALTY(0.05)`、occurred_at 缺失=unknown
  不加不减；external 不加分。选择 additive（当前 score=sim×weight 结构，additive 可解释、
  有界、不让 external 因时间超过 personal）。
- **时序**：semantic candidate → source strategy → temporal 调整 → content dedup → per-item
  cap → top_k（时间命中个人记录优先于无信号 chunk）。
- **明确不做的**：时间判断绝不基于文本关键词（必须用 metadata["occurred_at"]）；不硬过滤
  范围外；不删除 unknown；不新增 LLM/API/schema/rebuild；detect_query_intent 零改动。

## 三、验证

- 后端 pytest **452 passed**（443 + 9：时间范围 4 例、temporal 排序/范围外不伪装/旧 metadata
  兼容/personal 非时间零回归/recommendation 无时间加分 5 例）；cov 85.87% ≥70%。
- 前端 vitest **296 passed**；build 通过。
- 真实数据（6 查询 OLD/NEW 对比）：**OLD==NEW 完全一致**——真实库历史 memory 向量缺
  occurred_at（B-5 仅新写入带），时间信号对旧数据无效果；中性/个人/推荐零回归。
  **能力已实现，但当前真实数据覆盖不足，无法通过真实数据证明召回率提升**（需未来新写入的
  记忆产生 occurred_at 数据后生效）。
