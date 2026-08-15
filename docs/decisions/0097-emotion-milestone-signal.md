# 0097 · Phase 10-1-B-8：Emotion / Milestone Retrieval Signal

日期：2026-08-12
状态：已接受
基准：B-5（emotion/milestone metadata）、B-7（_compute_retrieval_score 统一 rerank）

## 一、决策

在 B-7 rerank 层启用已有 Memory metadata 的 emotion / milestone 确定性信号：
`final = base(semantic × source_weight) + temporal_adj + metadata_adj`。不改 API/schema/
embedding/chunking/source weight/top_k/candidate pool/intent keywords/per-item cap/Prompt/UI。

## 二、规则（app/retrieval.py）

- **emotion**：`_emotion_intent(query)`（印象/难忘/喜欢/讨厌/感动/开心/难过/震撼/怀念/情绪/
  感受/感想）+ `_emotion_matches`（chunk emotion 与 query 落在同一情绪组：感动/开心/怀念/
  难过/平静 五组；未知/空/非法 → 0；泛化词 情绪/感受/感想 对未知值视为匹配）→ `+0.08`。
- **milestone**：`_milestone_intent(query)`（第一次/第一个/初次/入坑/开始/起点/纪念/里程碑）
  + `milestone is True` → `+0.08`；false/缺失 → 0。
- 仅 personal source（memory/review/note）；external 永不获得 metadata 加分、不因缺 metadata
  被罚。emotion+milestone 叠加最多 `+0.16`；temporal 沿用 `+0.15/−0.05`。
- 普通 personal / recommendation / neutral query 无 emotion/milestone intent → 0（零回归）。
- **语义主导**：三信号全命中 = +0.31，仍不会让低相关结果压过高相关 personal（测试证明）。

## 三、验证

- 后端 pytest **471 passed**（458 + 13：emotion 命中/不匹配/无意图/缺失/非法、milestone
  true/false/缺失/无意图、external 不获 boost、temporal+emotion 叠加、emotion+milestone
  叠加、三信号语义主导、旧 metadata 全缺仍可检索、推荐 query 无自动加分）；cov 85.95% ≥70%。
- 前端 vitest **296 passed**；build 通过。
- 真实数据（12 查询 A/B，3 emotion + 3 milestone + 2 temporal+emotion + 2 neutral +
  2 recommendation）：**12/12 OLD==NEW**。真实库 memory chunk 覆盖 = **0**（现有个人记录全部
  来自 review 来源，无 direct memory 向量），emotion/milestone metadata 覆盖 = 0 → 信号对
  真实数据无可作用对象。**代码路径已验证，但真实召回提升暂无法证明**（需用户创建带
  emotion/milestone 的直接记忆并写向量后生效）。
