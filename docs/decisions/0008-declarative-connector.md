# 0008 · 声明式自定义数据源（Phase 4）

日期：2026-08-05
状态：已接受（Phase 4）

## 决策

### 声明式接入而非执行任意代码

AGENTS.md 明确"插件安全边界"：支持用户自建数据源时**走声明式配置
（HTTP 端点 + 字段映射规则）而不是执行任意 Python 代码**。Phase 4 据此
实现 `DeclarativeConnector`：

```json
{
  "name": "my-api",
  "display_name": "我的API",
  "base_url": "https://api.example.com",
  "search_endpoint": "/search?q={query}",
  "result_path": "data.items",
  "field_map": {"title": "name", "external_id": "id", "description": "summary"},
  "headers": {"Authorization": "Bearer {api_key}"}
}
```

- 只做 **HTTP GET + JSON 字段提取**，天然不执行任意代码；
- `field_map` 支持点号嵌套路径（`_dig`），`result_path` 取响应中的数组；
- `{query}` 占位符替换关键词；`headers` 值可为 `{env_var}` 引用环境变量，
  密钥不落库明文（`config_ref` 里存的是占位符而非明文）。
- 必填校验：base_url、search_endpoint、field_map 至少含 title/external_id。

### 配置持久化与自动恢复

- 用户通过 `POST /api/connectors` 创建的配置存 `sources` 表
  （`type="connector"`，`config_ref` 存 JSON）。
- 启动时 `connector_persistence.load_declarative_configs()` 读取并
  `register_declarative()` 恢复注册（配置非法则跳过并打印，不阻塞启动）。

### 联合检索降级

- Phase 3 的 federated 检索若单个 Connector 抛错会**整体 502**，阻断本地
  与其它源结果。Phase 4 改为：单个源失败记录到响应 `errors` 字典
  （`{source: message}`），**不影响其它源与本地结果返回**（HTTP 200）。
- 前端可据 `errors` 提示"某数据源暂不可用"，同时展示可用源的结果。

### 管理 API

- `POST /api/connectors`：创建声明式数据源（校验 → 注册 → 持久化）。
- `DELETE /api/connectors/{name}`：解除注册 + 删除持久化配置。
- `GET /api/connectors`：列出全部（含声明式，Phase 3 已有）。

## 权衡

- 声明式牺牲了代码级插件的灵活性，换取安全边界（个人项目线上风险最高
  的一环，AGENTS.md 明确优先声明式）。
- 密钥用"环境变量占位符"而非完整加密存储：个人本地项目够用；若未来
  需要强加密，可复用 `config_ref` 换实现，接口不变。
- 降级策略（返回 errors 而非 502）：更符合"联合检索"的产品语义——一个源
  挂了不该让整次检索失败。

## 已知限制

- 声明式 Connector 仅支持 search（无 get_detail / 分页 / 认证握手）。
- 无 UI 入口（用户需调 API 创建）；Phase 5 可加前端表单。
- 环境变量占位符是约定而非强制：用户把真实 key 写进配置也能存，文档需
  强调用占位符。
