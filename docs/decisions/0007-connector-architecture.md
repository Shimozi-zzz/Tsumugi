# 0007 · Connector 插件架构与联合检索（Phase 3）

日期：2026-08-05
状态：已接受（Phase 3）

## 决策

### 统一抽象（`app/connectors/base.py`）

- `Connector` Protocol：`name` + `manifest` + `search(query, **filters)` +
  `get_detail(external_id)`。任何实现该接口的类都可注册。
- `ConnectorManifest`：name / display_name / version / auth_type / base_url /
  rate_limit / capabilities，从各插件 `manifest.json` 加载（自描述）。
- `SearchResult`（轻量搜索结果）与 `ItemDetail`（完整详情）dataclass 统一
  跨数据源的数据结构。

### 注册与发现（`app/connectors/registry.py`）

- 运行时 `register(connector, enabled)` 手动注册；`discover()` 扫描
  `app/connectors/*/manifest.json + connector.py`，自动导入并注册
  （connector.py 暴露 `build_connector()` 工厂）。单个插件失败不影响其它。
- `set_enabled/is_enabled/get_enabled_connectors` 控制启用状态。

### Bangumi 实现

- `app/connectors/bangumi/`：manifest.json（auth_type=none，限流 20/min）
  + connector.py（search 用 `/v0/search/subjects`，get_detail 用
  `/v0/subjects/{id}`）。
- **限流**：进程内令牌桶（`_TokenBucket`），尊重 manifest 的
  requests_per_minute。
- **缓存**：SQLite 简单缓存表（`connector_cache`），同一 query/详情 TTL 600s
  内不重复打外部 API（AGENTS.md 要求"SQLite 简单缓存表即可"）。
- **normalize**：把 Bangumi subject 原始返回转成本地 Item 字段
  （title=name_cn 优先，type=external_ref，content=summary，image_url，
  source，external_id，raw_metadata，tags）。

### 数据模型扩展

- `Item` 补外部字段：`image_url`、`external_id`、`raw_metadata`(JSON)、
  `synced_at`；新增 `Source` 表（已注册数据源清单）。
- `ensure_schema()` 扩展：旧库 `ALTER TABLE` 补列。

### 联合检索 / 收藏入库 API

- `POST /api/search/federated`：子线程执行 本地向量检索 + 各已启用
  Connector 的 search()，结果合并返回 `{query, results(外部), local_results}`，
  前端按 source 加角标。本地检索失败不阻塞外部。
- `POST /api/items/save-external`：收藏入库（Save to Library）——仅存
  摘要/简介文本进向量库参与 RAG，不做全文抓取（版权边界）。
  同一 source+external_id 幂等（重复收藏返回已有条目）。
- `GET /api/connectors`：列出已注册/启用数据源。

## 权衡

- 联合检索结果**按来源分组**而非混合排序：外部结果没有与本地一致的语义
  分数，混排缺乏可信基准；分组便于前端区分"自己的资料"与"外部检索结果"
  （对应 AGENTS.md 的来源角标需求）。后续可做加权归一化混排（Phase 5）。
- 缓存用 SQLite 而非 Redis：个人本地项目够用、零依赖。
- 密钥管理：Bangumi 无需 key（auth_type=none）；预留 `config_ref` 字段，
  Phase 4 声明式接入带 key 的数据源时再实现加密存储。

## 已知限制

- 真实 Bangumi API 在本机网络不可达（timed out），实际数据验证待网络环境
  （单元/路由测试用 mock 覆盖 normalize/registry/联合检索逻辑）。
- 令牌桶为进程内实现，多进程部署时需共享限流（个人项目单进程即可）。
- 图片策略（"收藏入库时才缓存本地缩略图"）暂未实现：当前直接存外部 image_url
  链接，仅元数据落库，符合"默认展示原始链接"的最低要求。
- 联合检索为"全量已启用 Connector"逐一遍历，Connector 数量多时可并行化
  （当前最多几个，串行足够）。
