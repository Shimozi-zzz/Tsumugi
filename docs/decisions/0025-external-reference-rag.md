# 0025 · 外部资料本地化下载 + 参与 RAG 检索（可区分来源）

日期：2026-08-08
状态：已接受

## 背景与问题

此前"收藏入库"（`ingest_external`）只把简介摘要存进 `raw_metadata`，完整资料
（简介+角色小传）不参与语义检索；且检索结果无法区分"用户自己写的内容"与
"外部下载的百科资料"。用户问"我对某角色怎么看"时，官方简介文本可能挤掉
自己的书评——两类内容混为一谈。

## 决策 1：Chunk 增加来源类型标记

- `Chunk` 新增 `source_type`（`note` / `review` / `external_reference`）与
  `connector`（仅 external_reference 记录数据源名）两列；
- 走 `ensure_schema` 迁移（SQLite ALTER 加列 + **回填**历史值）：
  - `review_id IS NOT NULL` → `review`（connector 留空，避免混淆来源）；
  - item 为 `external_ref` → `external_reference` + `connector=item.source`；
  - 其余 → `note`。幂等：只填 NULL，重复执行不产生新改动。
- **检索层权威来源是 SQLite**（`Chunk.source_type/connector`）：新写向量同时带
  Chroma metadata `source_type`（快速路径），历史向量无 metadata 时按
  embedding_ref 批量回查 DB 兜底——不依赖 Chroma 元数据迁移，降低启动耦合。

## 决策 2：检索层区分来源 —— 加权 + 可选硬过滤（不改变核心检索逻辑）

目标：默认问答优先/正常检索用户自己的 note/review，外部百科只作事实性补充，
**不无差别混合排序**；同时支持"只看我的内容"的硬过滤。为此：

- **加权**：`score × weight(source_type)`，`note/review`=1.0，
  `external_reference`= `settings.external_reference_weight`（默认 **0.4**）。
  - 为什么 0.4：足够把"同相似度的百科内容"压到用户自己内容之后（主观问题），
    但事实性问题（如"男主是谁"，百科 chunk 相似度显著更高，0.9×0.4=0.36 >
    泛泛感想 0.3）仍能进入前列。太接近 1（如 0.9）对主观问题保护不足，太低
    （如 0.2）会让事实性补充几乎不可用。
  - 候选池从 `top_k*4` 提到 `top_k*6`：补偿"外部百科被压低后"的用户内容召回
    （避免重排后 top_k 出现空洞）。
- **硬过滤**：`QueryRequest.source_types`（如 `["note","review"]` 只看自己写的），
  检索后按来源类型过滤候选，再进入去重/排序。
- 应用顺序：解析来源 → 过滤 spoiler（ADR 0017）→ source_types 过滤 → 内容去重
  → 加权排序 → 按 item 去重 → 截断 top_k。

## 决策 3：收藏入库时下载并切分完整资料

- `_save_external_sync` 在调 `get_detail` 的既有位置，把响应构建为完整参考文本
  `build_reference_text(detail)`：**作品简介 + 基本信息（原名/日期/标签等）+
  每个角色的小传小节（## 角色名 + relation + summary + 声优）**。Markdown 标题
  天然成为语义块边界，复用现有 heading-aware 切分（ADR 0001）；
- `ingest_external` 新增 `reference_text` 参数：新条目切分 reference_text 入库
  （`source_type=external_reference`），否则退回切分 content（保持旧行为）；
- `raw_metadata.detail.metadata.reference_text` 存完整资料文本：既做追溯，也用于
  **判重**——重收藏/刷新时若文本未变则不重建 chunk（避免反复 re-embedding）。

## 决策 4：历史收藏批量补齐脚本（复用角色墙 backfill 模式）

`external_refs.backfill_external_reference(limit, source, db)`：
- 找 `source != local` 且 raw_metadata 缺 `reference_text` 的条目，每次最多补
  `limit` 条，**可重复调用继续推进**（缺哪条补哪条，已补齐跳过，单条失败跳过）；
- **限流**：直接复用各 Connector 的 `get_detail`（内部令牌桶 `_bucket.acquire()`），
  不另起限流，避免重蹈"同步阻塞 119 秒"（无约束批量拉取）的教训；
- **批次大小 `limit=5` 的理由**：Bangumi manifest 限速 20 req/min，而
  `get_detail` 实际发 2 个请求（subject + characters），即满速约 10 条目/分钟；
  每次手动触发补 5 条（半分钟量级）观察明显推进、又留足余量；脚本 CLI 与
  `POST /external/backfill-reference`（单飞后台线程，返回即走）共用同一函数。

## 决策 5：详情页/角色墙优先读本地，缺失/手动刷新才请求

现状核查：`/items/{id}/detail` 与 `/characters` 都**已优先读本地** `raw_metadata`
（角色墙只在缺 detail 时由 `backfill_bangumi_details` 非阻塞补拉）。本轮补充：

- 角色墙的懒加载补详情**顺带重建 external_reference chunk**（同一份 get_detail
  响应不浪费，Bangumi 批量导入的历史条目借此自动补齐 RAG 资料）；
- 新增**手动刷新**入口：`POST /items/{id}/refresh-external`（重新下载最新完整
  资料，更新 raw_metadata + 重建 chunk，受令牌桶约束）与
  `POST /external/backfill-reference`（批量，单飞）。不把外部资料锁死成一次性
  快照。

## 决策 6：RAG 回答来源标注

- `build_context_prompt`：note → `（我的笔记）`，review → `（我的书评：标题）`，
  external_reference → `（百科资料：connector）`；
- system prompt 明确要求：主观类问题优先依据用户自己的书评/笔记，外部百科只作
  事实补充；引用时标注来源类型（"根据你的书评…" vs "根据百科资料…"）；
- SSE `sources` 事件携带完整字段（source_type/connector/review_title），前端
  来源角标显示"我的书评/我的笔记/百科·bangumi"，视觉区分两类内容。

## 明确不做

- 不改变 note/review 的核心检索逻辑（只新增一个区分维度）；
- 不做"用户手动选择某条目是否下载完整资料"的细粒度 UI（默认收藏即下载）；
- 批量补齐不做成完整后台任务调度系统（"能跑、可控速度"即可）。

## 实测验证（2026-08-08，真实 Bangumi + 本地 Ollama）

1. 真实收藏「命运石之门」（Bangumi id=3154）→ 入库 22 个
   `external_reference` chunk（connector=bangumi），详情 18 个角色，
   reference_text 7081 字符。
2. 事实性问题"命运石之门的男主角是谁" → 检索 top 为 external_reference（score
   0.2025），回答正确给出"冈部伦太郎"，且来源标注为「百科资料」。
3. 写入一条自己的书评后问"我对命运石之门的看法" → **top 命中的是 review
   （score 0.71），外部百科被压到 ~0.19**；回答引用「我的书评」。
   → 用户自己的内容不被外部百科挤掉，两类来源清晰可分。
4. `POST /items/60/refresh-external` 刷新成功（characters/reference 保持不变）。

## 测试

- pytest **334 passed**，覆盖率 85.6%（新增：迁移回填、collect 下载切分、
  检索加权/过滤、backfill 分批/限流/失败跳过、refresh 端点）；
- 前端 build 通过，vitest **81 passed**。
