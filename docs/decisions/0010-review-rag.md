# 0010 · Review 读后感接入 RAG 检索

日期：2026-08-06
状态：已接受（Phase 5 后功能迭代）

## 背景

让每个作品条目（Item）支持多条读后感/书评（日记式记录），且书评内容需要
参与知识库的语义检索。核心设计难点：**Review 内容如何接入现有 RAG 检索，
且与条目自身内容不混淆**。

## 决策

### 复用现有 Chunk 机制 + `Chunk.review_id` 区分来源

不另建向量表、不复制检索管道，直接复用 `ingest.py` 已有的
"切分 → embedding → Chroma + Chunk 行"机制：

- `Chunk` 表新增可空列 `review_id`：
  - `NULL` = 条目自身内容（note/external_ref 原文）；
  - 非空 = 该条 review 的内容。
- Review 创建时：`split_text(content)` → `embed_texts` → 写入 Chroma +
  Chunk 行，Chroma metadata 带 `item_id` + `review_id` + `chunk_index`，
  Chroma id 形如 `review{id}_chunk{i}`。

### 检索来源区分

- `retrieve_chunks` 从 Chroma metadata 读 `review_id`：
  - 有 → `RetrievedChunk.source_type="review"`、`review_id`、`review_title`；
  - 无 → `source_type="item"`、`review_id=None`。
- `rag.build_context_prompt` 对 review 来源标注
  `来源：《条目名》（读后感：标题）`，LLM 能区分"原作内容 vs 我的感想"。
- 去重/排序逻辑不变（按 item 维度去重仍适用，review chunk 与 item chunk
  同属一个 item）。

### 向量同步清理（复用 ingest 的"反向删除"模式）

- **编辑**：content 变化时先按 `review.chunks` 的 `embedding_ref`
  `collection.delete(ids=...)` 删除旧向量，`db.flush()` 后重新写入。
- **删除**：删除全部向量 + Chunk 行 + Review 行。
- **创建失败**：`db.rollback()` 后按 `review_id` 查询已写入的 refs 反向删除，
  避免孤儿向量（与 `ingest.ingest_text_document` / `ingest_external` 一致）。

### 数据模型 / API

- `Review` 表：`id / item_id(FK,级联) / title(可空) / content / rating(0-10) /
  status(想看/在看/看完/搁置/弃坑) / spoiler(0/1) / created_at / updated_at`。
- 一个 Item 多条 Review（无唯一约束）。
- `ensure_schema` 迁移：chunks 加 `review_id` 列；reviews 表由 create_all 建。
- API：`POST /items/{id}/reviews`、`GET /items/{id}/reviews`（倒序）、
  `PATCH /reviews/{id}`、`DELETE /reviews/{id}`、`GET /reviews`（全局）。
- 大众评分对比：外部收藏（source≠local）从 `raw_metadata.rating.score` 取
  大众分，响应带 `public_rating`，前端并排展示"大众 ★x / 我 ★y"。

## 权衡

- 复用 Chunk 而非独立 review 向量表：避免复制检索/去重/清理逻辑；代价是
  `Chunk.review_id` 引入了"来源维度"，检索时需读 metadata 区分（已实现）。
- 评分/状态存 Review 行而非 raw_metadata：是"我的主观记录"，与外部 API
  原始数据分离。
- spoiler 只影响前端折叠展示，不做后端过滤（检索仍可命中剧透内容，
  由用户决定是否展开）——保证"知识库检索完整性"优先。

## 已知限制

- review 的 rating 与 item 的"大众评分"并存展示，但无聚合（如加权平均）。
- spoiler 内容仍参与向量检索（不过滤），仅前端默认折叠。
- status 是自由字符串校验（SQLite 无 enum），非法值在应用层拒绝。
