# 0094 · Phase 10-1-B-5：Metadata Signal Preparation

日期：2026-08-12
状态：已接受
基准：Phase 10-1-B-4 审计（P2-1：temporal 无时间信号 → 建议 B Metadata Signal Preparation）、
ADR 0051（Memory 语义检索）

## 一、决策

为后续时间/情绪/里程碑检索与 rerank 铺设安全 metadata 基础：仅扩展**新写入**的向量
metadata，不重建历史向量、不改变检索排序行为。本阶段**不启用**时间/情绪/里程碑检索或
rerank。

## 二、Metadata 变化（app/memories.py）

- 新增 `_meta_primitive(value)`：datetime→ISO-8601 字符串；str/int/float/bool 保持；
  None/空由调用方省略；复杂对象转 str——保证 Chroma 写入安全。
- 新增 `_memory_vector_meta(mem, chunk_index)`：保留既有键（item_id / memory_id /
  chunk_index / source_type）+ 记忆级信号：
  - `occurred_at`（若存在，ISO 字符串）
  - `emotion`（若存在）
  - `milestone: true`（当 `source_type == "milestone"`；Memory 无独立 milestone 列，
    milestone 由既有 source_type 语义表达，非新字段）
  - 同一 memory 的多 chunk 共享同一组记忆级 metadata（chunk_index 除外）。
- **Review**：`_write_review_vectors` 不动——Review 模型无 occurred_at/emotion/milestone
  字段，按任务"不新增 schema、不虚构字段"不写任何新键。
- `backfill_memory_vectors` 只补缺失向量（幂等），非 metadata 升级入口；历史向量缺新键
  仍正常检索（retrieval 不读取这些键）。

## 三、验证

- 后端 pytest **443 passed**（438 + 5：memory metadata 含 occurred_at/emotion、milestone
  标志、None 不写键且多 chunk 共享/索引各异、review 不虚构信号键、旧 metadata 缺新字段仍
  可检索）；cov 85.73% ≥70%。
- 前端 vitest **296 passed**；build 通过。
- 回归：既有 retrieval/prompt/API/schema/frontend 全部未动（git diff 仅
  app/memories.py + 2 测试文件）。
