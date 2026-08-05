# 0006 · 标签系统与结构化筛选（Phase 2）

日期：2026-08-05
状态：已接受（Phase 2）

## 决策

### 检索侧：标签过滤支持交集

- `retrieve_chunks(..., tags, tag_match="any"|"all")`：
  - `any`（默认）：包含**任一**指定标签的 item 命中；
  - `all`：必须同时包含**全部**指定标签（交集）。
- 实现：SQL `JOIN item_tags/tags` + `GROUP BY item.id` + `HAVING
  count(distinct tag.id) >= len(tags)`（all）或 `>= 1`（any），筛出 item_ids
  后作为 Chroma `where` 过滤。SQL 层语义明确、单条查询，避免多次查询拼集。
- `QueryRequest` 新增 `tag_match`，search/rag 路由透传。

### 列表侧：结构化筛选 + 分页信封

- `GET /items` 改为返回 **`{total, items}`**（原来直接返回数组）。
  - `total` 为**筛选后**总数（不受分页影响），供前端分页/计数。
  - 筛选参数：`tag`（可重复，`?tag=a&tag=b`）、`tag_match=any|all`、
    `type`（note/image）、`source`。
- **关键实现注意**：FastAPI 里 `Optional[List[str]]` query 参数若不显式用
  `Query()` 标注，会被当作**标量**处理，多个值/列表绑定为 None（实测）。
  必须写 `tag: Optional[List[str]] = Query(None)`。

### 标签管理 API

- `GET /tags`：返回 `[{id, name, count}]`（count 为关联条目数）。
- `PATCH /tags/{id}`：重命名；新名冲突返回 409。
- `DELETE /tags/{id}`：删除标签（先清 `item_tags` 关联，不删条目）。
- `POST /tags/merge`：`{target_tag_id, source_tag_ids}` —— 把源标签全部并入
  目标（目标关联去重），删除源标签。

### 前端

- 资料列表适配 `{total, items}`；新增标签筛选条（标签 pill + any/all 切换 +
  类型筛选）；新增标签管理面板（重命名/删除/合并）。

## 权衡

- `all`（交集）用 `GROUP BY + HAVING count(distinct)` 而非多次 `JOIN`：
  单查询、可读、通用（PostgreSQL 迁移也兼容）。
- 合并标签在**数据库层**完成（重新关联 + 删源标签），而非应用层搬数据，
  保证关联唯一性与一致性。
- 标签筛选 UI 用"标签 pill 点选"而非多选框：视觉直接、操作少。

## 已知限制

- 未做标签分页（标签数量通常有限）。
- `ItemFilter` schema 已定义但列表接口用 query 参数实现（更适合 REST 语义），
  该 schema 暂未使用（可留作未来 POST 批量筛选）。
- 标签搜索接口未做（可按名字模糊搜索，后续需要时补）。
