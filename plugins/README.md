# Tsumugi 第三方插件（代码级数据源）

> ⚠️ **安全声明（务必先读）**
> 插件是**你手动放进本目录的第三方 Python 代码**。插件运行时拥有与 Tsumugi
> 后端**完全相同的系统权限**：可以读写你的知识库文件、访问网络、读取环境变量
> 等。Tsumugi **不做沙盒隔离**、**不会联网下载或自动运行任何插件**——请只安装
> 你信任来源的插件，并在安装前审查其代码。风险以显式提示暴露（设置页「插件」
> 面板 + 首次检测到插件时的一次性确认），而不是假装做了隔离。

---

## 这是什么

把一个新的数据源"上架"进来，除了用内置 Connector / 声明式配置，你还可以写一个
**代码级插件**（复用统一的 Connector Protocol）。与内置 Bangumi/萌娘百科/VNDB
完全同构。

## 信任模型（设计约束，见 ADR 0027）

- ✅ 允许：从 GitHub / 社区下载插件的 `.py` 文件，放进 `plugins/` 目录，**重启
  应用**后加载生效。
- ❌ 不允许：应用内置"插件市场 / 一键远程安装并自动运行"。
- ❌ 不做沙盒：插件与后端同权限，风险靠"显式告知 + 本地文件来源"控制。
- 加载失败的插件会被**优雅跳过**（记录错误日志，不影响应用启动，可在设置页
  查看失败原因）。

## 目录结构

每个插件是一个子目录（**名字以 `_` 或 `.` 开头的目录不会被加载**，例如本目录的
`_template/` 是参考示例）：

```
plugins/
├── README.md
├── _template/hello_world/     # 最小可用的参考示例（不会被自动加载）
│   ├── manifest.json
│   └── connector.py
└── my_connector/              # 你的插件（放在这个层级）
    ├── manifest.json
    └── connector.py
```

## manifest.json 格式

```json
{
  "name": "my_connector",
  "display_name": "我的数据源",
  "version": "0.1.0",
  "auth_type": "none",
  "base_url": "https://api.example.com",
  "rate_limit": { "requests_per_minute": 20 },
  "capabilities": ["search", "get_detail"]
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | ✅ | 全局唯一标识（与已注册数据源冲突会导致加载失败） |
| `display_name` | | 设置页显示名，缺省取 `name` |
| `version` | | 插件版本 |
| `auth_type` | | `none` / `api_key` / `oauth` |
| `base_url` | | 数据源 API 根地址 |
| `rate_limit.requests_per_minute` | | 限流（令牌桶），尊重数据源速率限制 |
| `capabilities` | | 支持的能力；声明 `get_detail` 则**必须实现** `get_detail()` |

## Connector 接口规范

`connector.py` 必须暴露 `build_connector()` 工厂函数，返回一个实现了以下接口的
对象（`name` 和 `manifest` 会在加载时由 `manifest.json` 覆盖，代码里不用管）：

```python
from app.connectors.base import SearchResult, ItemDetail

class MyConnector:
    def search(self, query: str, **filters) -> list[SearchResult]:
        """调用外部 API 搜索，返回轻量结果（标题+封面+简介）。必选。"""

    def get_detail(self, external_id: str) -> ItemDetail:
        """拉取完整详情（角色等）。manifest 声明 get_detail 时必须实现。"""

def build_connector():
    return MyConnector()
```

- `SearchResult`：`source / title / external_id / subtitle / description /
  image_url / rating / tags / raw`；
- `ItemDetail`：`source / title / external_id / description / image_url /
  metadata`；
- 插件内用**绝对导入**访问框架能力：`from app.connectors.base import http_get,
  http_post, SearchResult, ItemDetail, RequestCache` 等；出站代理用
  `self.proxy_url`（registry 自动注入，直连为 `None`）；
- `search` 里建议做请求缓存（参考内置 Connector 的 `RequestCache`）与令牌桶
  限流（`TokenBucket`），避免打爆数据源。

## 最小示例

直接复制 `_template/hello_world/` 目录，改 `manifest.json` 的 `name`/`base_url`
与 `connector.py` 的实现即可（示例调用了 Open Library 公开搜索 API）。

## 如何调试

1. 重启应用后查看启动日志，带 `[plugin]` 前缀的行是插件加载记录：
   - `[plugin] 已加载 <name>` → 成功；
   - `[plugin] 加载 <目录名> 失败：<原因>` → 失败（单个失败不影响其它插件）。
2. 设置页 → 「插件」面板：可看到已加载插件列表、加载失败列表与风险提示。
3. 常见失败：
   - `manifest 缺少 name` / JSON 格式错误；
   - `connector.py 必须暴露 build_connector()`；
   - `build_connector() 返回了 None`；
   - `插件必须实现 search(...)`；
   - `manifest 声明了 get_detail 能力，但插件未实现 get_detail()`；
   - `数据源名 '<name>' 已被占用`（与内置/其它插件重名）。
4. 语法错误（如 Python `SyntaxError`）同样被捕获并记录，不会导致应用崩溃。

## 安全注意事项

- 只安装你信任来源的插件，安装前审查代码；
- 插件可访问你的全部知识库数据与环境变量，**不要**把含密钥的插件分享给不可信
  的第三方；
- 插件失败会被跳过，但**已加载的插件是即时生效的**——移除插件文件并重启即可
  卸载；
- Tsumugi 不会自动更新插件，也建议你手动核对新版本代码后再替换。
