# 0015 · Connector 出站代理配置 + 萌娘百科 Connector

日期：2026-08-06
状态：已接受

## 背景

Bangumi API 需要代理才能访问，但之前"每个海外数据源临时处理"不可持续。
本轮做两件事：

1. **Connector 出站代理配置**（系统性方案）：任意已注册 Connector
   （内置/声明式/新增）可选配置 HTTP/HTTPS 出站代理，不配置则直连。
2. **萌娘百科 Connector**：国内直连的 ACG 向数据源，验证"新增数据源 =
   写一个实现 + 一份 manifest + 注册"的插件化流程对第二个内置源依然成立。

## 一、出站代理配置方案

### 存储（复用 sources 表 config_ref，不新起存储）

- 单独一行固定名 `name="connector_settings", type="settings"`，config_ref
  存 JSON：`{"<connector_name>": {"proxy_url": "..."}}`。
- 为什么不是每 Connector 一行：`Source.name` 是唯一键，声明式数据源已
  占用各自 name 的行（type="connector"），再插 settings 行会撞唯一约束；
  用一个固定行名存全量 dict 天然避开冲突，也与"一处读取、一次注入"契合。
- 声明式 Connector 的 `proxy_url` 不塞进它自己的 config JSON——统一走
  同一个 settings blob，避免两套存储路径。DeclarativeConnector 同时兼容
  配置里内联 `proxy_url`（校验逻辑一致）。

### 运行时注入

- `registry.apply_settings(settings)`：把 settings dict 里的 proxy 写到
  每个已注册实例的 `proxy_url` 属性；`main.py` 启动时 discover + 恢复声明式
  之后调用；保存代理时路由再调用一次（更新即时生效，无需重启）。
- Connector Protocol 增加可选属性 `proxy_url: Optional[str] = None`。
- HTTP 请求统一走 `base.http_get(url, proxy=...)`（httpx 原生 `proxy`
  参数，proxy=None 即直连，默认行为不变）。

### 代理地址的 SSRF 校验（关键决策）

复用 `ssrf.py`，**默认放行回环**（`allow_loopback=True`，可显式关掉）：

- **判断（初版失误 → 已修正）**：最初实现**不放行回环**，理由是"代理是
  转发出站流量的中转，没有 Ollama 那种本机合法服务理由"。但实测发现这是
  **致命误判**——本地代理软件（Clash/V2Ray 等，国内最常见的代理使用方式）
  **默认就监听在 127.0.0.1**，而这个功能正是为"Bangumi 需要代理"设计的。
  不放行回环等于把最主要的目标场景整个挡掉，功能形同虚设。
- **修正后的判断**：代理地址是用户在**自己设置页里主动配置的本地/受信
  地址**，风险模型与 Ollama 场景一致（坑位 #29 同款模式），不同于
  Connector 处理不可信输入 URL 的场景。放行**仅回环**（127.0.0.1 /
  localhost / ::1），**其余私网段（10.x / 172.16.x / 192.168.x /
  169.254.x 云元数据）仍然拦截**——只放行回环，不整体放宽。
- **时机**：
  - 保存/测试连接：`validate_proxy_url(proxy_url)` 校验（协议白名单 +
    私网/链路本地/CGNAT 拒绝 + 回环放行 + `resolve=True` DNS 解析，防
    "域名解析到内网"的 rebinding 场景），违规 HTTP 400；
  - 请求路由时：保存已校验过，不再逐请求重解析（代理是管理级设置，
    非每请求用户输入；目标 base_url 自身仍有其请求期校验）。
- 复用上一轮坑位 #29 的教训：同一套校验逻辑，按场景区分例外，
  不为新场景另起一套；`validate_proxy_url(allow_loopback=False)` 保留
  "严格模式"入口供未来收紧。

## 二、萌娘百科 Connector

### 真实访问的发现（决定实现路径）

对 `zh.moegirl.org.cn/api.php` 实测（2026-08-06）：

| 模块 | 匿名可用？ |
| --- | --- |
| `action=query&titles/...&prop=info` | ✅ |
| `prop=pageimages`（缩略图） | ✅ |
| `prop=categories` | ✅ |
| `prop=extracts`（TextExtracts 纯文本简介） | ✅ |
| `action=query&generator=search` | ✅（等效于 list=search） |
| `action=opensearch` | ✅ |
| `list=search` | ❌ action-notallowed |
| `action=parse` / `prop=revisions`（wikitext） | ❌ 被禁 |
| `index.php?action=raw` | ❌ 返回"未授权操作"HTML |

另外**必须带浏览器 User-Agent**，默认 `Tsumugi/0.1` 会被 401。

### 因此的实现

- **search**：任务要求用 `list=search`，但该模块被禁 → 用
  `generator=search`（同一底层搜索，返回 pages 数组，顺带取 extracts +
  pageimages，搜索列表直接带简介和封面图，减少后续请求）。**如实偏差**。
- **get_detail**：`action=query&pageids={id}&prop=info|pageimages|
  categories|extracts&cllimit=50&exintro=1&explaintext=1`——纯文本简介、
  封面、分类一次拿全。
- **normalize()**：任务预期要解析 wikitext Infobox，但真实 API **禁止
  wikitext**（revisions/parse/raw 全被拦）。主路径直接用结构化字段：
  - 简介 = `extracts`（比手写 wikitext 解析更干净）；
  - 封面 = `pageimages.thumbnail.source`（正是任务要求的 pageimages 模块）；
  - 标签 = `categories`（过滤维护类分类，如"使用标题替换的页面""分离袖子"
    "带有无法存档的失效链接的条目"等，用精确片段 blocklist）。
  - **保留 wikitext Infobox 解析兜底**：若 payload 带 `wikitext`（其它开放
    wikitext 的 MediaWiki 实例/自建 wiki），用 `_parse_infobox`（顶层
    `{{...}}` 模板 + `| 字段 = 值`，处理嵌套大括号）+ `_strip_wikitext`
    （注释/模板/链接/引用/粗斜体清理）补全简介/封面/萌点标签——覆盖任务
    要求的"模板字段提取逻辑"，且用贴近萌娘百科《人物信息》模板的真实样例
    测试。

### 已知局限（如实标注）

- 萌娘百科正式 API 不开放 wikitext，Infobox 解析路径目前对萌娘百科本体
  不可达，只对其它开放 wikitext 的 MediaWiki 生效；`normalize` 主路径
  依赖 TextExtracts 插件（本源已确认可用）。
- `_parse_infobox` 只取顶层竖线字段、首项胜出，不处理复杂模板嵌套
  （`{{模板|...}}` 内的字段、同一字段多次出现取首个）。
- 维护类分类过滤靠 blocklist 启发式，可能漏/误过滤少数分类（文档化）。
- 需要浏览器 UA 是萌娘百科的服务端要求，写入实现并在 docstring 说明。

## 权衡

- **单行 settings 存储 vs 每 Connector 一行**：单行避免唯一键冲突、一次
  读取一次注入；代价是"connector_settings"这个名字被占用（已足够冷门，
  可接受）。
- **代理校验放行回环 vs 不放行**：最终选择**默认放行回环**（Clash/V2Ray
  默认监听 127.0.0.1，是代理配置最主要的目标场景；初版"不放行"是误判，
  已修正，见"关键决策"一节）。放行仅回环，私网/链路本地仍拦；保留
  `allow_loopback=False` 严格模式入口供未来收紧。
- **generator=search 替代 list=search**：前者受限于 `gsrlimit`（默认
  ~10-50），搜索结果规模够联合检索用；响应是 page 数组而非 search 数组，
  解析逻辑按 pages dict 处理。

## 测试

- `tests/test_proxy.py`（+31 用例）：代理 SSRF（私网 10.x/172.16.x/
  192.168.x/云元数据拒绝、**回环 127.0.0.1/localhost/::1 与公网放行**、
  严格模式 allow_loopback=False 仍拒回环、域名解析到内网拒绝）、
  Bangumi/声明式有代理与无代理的请求路由（mock httpx 验证 `proxy`
  参数）、registry 注入、persistence 往返与清除、API 保存/清除/测试代理
  （私网 400、**Clash 默认 127.0.0.1:7890 保存成功**、连通成功、连接失败
  降级）。
- `tests/test_moegirl.py`（+18 用例）：基于真实抓取格式的
  search/get_detail/normalize mock 数据、维护类分类过滤、wikitext
  Infobox 兜底、错误映射、manifest/discover 注册。
- 全量 pytest **232 passed**（本轮 +7，含回环放行与 Bangumi POST 修正用例），
  覆盖率 83.07%；vitest 9 passed；`npm run build` 通过。

## 实测（本轮追加：Clash 本地代理 + Bangumi 真实打通）

本机实测 Clash Verge（verge-mihomo，mixed 端口 `127.0.0.1:7897`）：

- **回环放行生效**：`POST /api/connectors/bangumi/proxy` 保存
  `http://127.0.0.1:7897` 成功（此前会被 400 拒绝）。
- **Bangumi 首次真实返回数据**（此前直连一直超时，从未成功）：
  - federated 检索"辉夜大小姐"→ `errors: {}`，**bangumi 返回 10 条**，
    首条《辉夜大小姐想让我告白 ~天才们的恋爱头脑战~》带真实简介与
    lain.bgm.tv 封面图；moegirl 同时返回 10 条，互不干扰；
  - `get_detail("135218")` 经代理返回真实标题/简介/封面/标签。
- **打通后暴露的既有 bug（已修）**：Bangumi v0 搜索端点是 **POST**
  `/v0/search/subjects`（body `{"keyword":...}`），connector 原来用 GET
  会返回 404——此前被"直连超时进 errors 降级"掩盖，代理一打通立即暴露。
  已把 `_request` 支持 POST 分发、`search` 改用 POST body，并补 2 个用例
  （POST + keyword body、type filter）。
