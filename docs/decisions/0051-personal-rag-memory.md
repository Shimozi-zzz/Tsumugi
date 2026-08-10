# 0051 · Personal RAG：Memory 进入个人语义检索（P7）

日期：2026-08-10
状态：已接受
基准：docs/product-brief-v1.1.md（十二节"Memory 是语义容器，RAG 检索其中的素材"）+
PROJECT_AUDIT P7 + AGENT_UI v2.2【AI·检索记录】

## 一、范围

让**直接 Memory**（轻量文字 / 里程碑，P3 起）的文本进入**个人语义检索**：创建时切分
summary → embedding → Chroma（`source_type=memory`），RAG 回答的引用标注为"（我的记忆）"，
与"我的书评/我的笔记/百科资料"并列区分。

**本轮明确不做**：Review/Note 本已参与 RAG（ADR 0025），无需重复索引；把 external_reference
加权逻辑改动；检索台 L4（AI 记忆理解）。

## 二、核心决策

1. **Memory 内容以素材形态进 RAG（延续 ADR 0041）**：不把 Memory 表整个向量化，而是把
   **直接 Memory 的 summary 文本**（就是它的素材）切分建 chunk（`source_type=memory`，
   `Chunk.memory_id` 关联）。review 类记忆的素材是底层 Review（已参与 RAG），不重复建。
2. **生命周期与 Review 向量同模式**：创建直接 Memory 时写向量（失败回滚+清理）；删除时
   删向量与 chunk；启动时 `backfill_memory_vectors` 为缺向量的历史直接记忆幂等补齐。
3. **来源区分**：`source_type=memory` 权重 1.0（用户自己的内容，与 note/review 同级，非
   外部百科的 0.4）；RAG 引用标注"（我的记忆）"；前端来源角标"我的记忆"。
4. **不新建表**：`Chunk` 加 `memory_id` 列（镜像 review_id），`Memory.chunks` 关系。

## 三、接口/实现

- `app/memories.py`：`_write_memory_vectors` / `_delete_memory_vectors`；
  `create_direct_memory` 写向量；`delete_direct_memory` 删向量；
  `backfill_memory_vectors(engine)`（启动时调用）；
- `models.py`：Chunk.memory_id + Memory.chunks（cascade）；
- `database.py`：chunks 迁移加 memory_id 列；
- `app/rag.py`：来源标注 "（我的记忆）"；`DesktopView.sourceTypeLabel` 加 "我的记忆"。
- 检索/权重：无需改 retrieval（source_type 权威解析已支持任意值，非 external 权重 1.0）。

## 四、测试与实测

- pytest **420 passed**（+2：直接 Memory 建向量可检索（source_type=memory）、删除清向量与
  chunk、backfill 幂等）。
- vitest **212 passed**（来源角标映射），build 通过。
- 实测见简报（真实库创建一条轻量记忆 → Chunk 落库 → 语义问答命中标注"我的记忆"）。
