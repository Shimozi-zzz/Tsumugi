# 0002 · 检索排序与去重

日期：2026-08-05
状态：已接受（Phase 1）

## 决策

### 排序

- Chroma 按余弦距离升序返回（collection 使用 `hnsw:space=cosine`，embedding
  已归一化），`score = 1 - distance` 换算为相似度。
- 返回后**显式按 score 降序**再排序一次，不依赖 Chroma 的隐式顺序，便于
  测试与后续接入其他向量库时行为一致。

### 去重（两阶段）

1. **内容去重**：完全相同的 chunk 内容只保留一条。防御同一文档重复导入
   或重叠切分产生的重复块。
2. **按条目去重（cap）**：同一 Item 最多保留 `max_chunks_per_item` 条
   （默认 1），避免单篇长文霸占整个 top-k，保证检索结果跨条目多样化。

### 参数与实现

- Chroma 查询时 `n_results = max(top_k * 4, 20)`，为去重留足候选。
- `tags` 过滤：**先 SQL 筛 item_ids，再作 Chroma `where` 条件**。SQL 侧用
  `JOIN` 到 `item_tags`/`tags`，`IN` 语义为"包含任一指定标签"。无匹配 item
  时直接返回空列表，不查向量库。
- 实现注意：chromadb **1.0.x 的 `{"$in": [...]}` 校验有 bug**（`validate_where`
  对嵌套操作符误报）。实际用 `$or` + 等值条件构建：
  `{"$or": [{"item_id": id} for id in ids]}`（单 id 直接用等值），
  等价且在各版本 Chroma 上都可用。
- item 标题与标签在结果返回前用**批量查询**回填，避免逐条 N+1。

## 放弃的方案

- **MMR（多样性重排序）**：原规划 Phase 1 做的 `calculate_diversity_score`
  推迟到 Phase 2+。理由：MVP 阶段 top_k 通常 ≤ 5，per-item cap 已提供了
  足够的多样性；MMR 需要额外的候选集与计算，收益在结果少时不明显。
- **同条目保留全部 chunk**：会让相关度最高的单篇文档占据全部结果，
  缩小上下文覆盖面，故用 cap=1 作默认。
- **结果合并的加权混合排序（本地 + 外部源）**：Phase 3 联合检索再做。

## 小决策

- `max_chunks_per_item` 默认 1，可在 `QueryRequest` 中覆盖。
- 空查询、空 collection、tag 无匹配，均返回 `[]`（而非报错）。

## 已知限制

- 同一 Item 被截断/重复导入时，Chroma 中会残留重复向量（SQLite 层无
  content hash 去重）。已靠"内容去重"缓解，彻底方案（导入前按标题+内容
  hash 判重）留待后续。
