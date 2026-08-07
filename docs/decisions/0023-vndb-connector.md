# 0023 · VNDB Connector 接入（第三个数据源验证案例）

日期：2026-08-06
状态：已接受

## 背景

第三个内置数据源（第二个"国内直连以外的外源验证"），验证 Connector 抽象对
**POST + JSON body 风格** API 的适配（Bangumi/萌娘百科都是 GET+query 参数）。
按"实测优先于猜测"（Bangumi 那轮的教训）先实测再实现。

## 一、实测结论（写实现前先用最小请求验证）

| 项 | 实测结果 |
| --- | --- |
| 网络可达 | `api.vndb.org` **直连可达**（无需代理；代理配置机制保留，经现有 Connector 代理配置按需启用） |
| 是否需要 token | 公开 VN/角色查询**不需要 token**（只做搜索/详情；不做用户列表，故不做 OAuth，避免过度设计） |
| HTTP 风格 | POST `https://api.vndb.org/kana/vn|character`，body = `filters` 数组 + `fields` 逗号串 |
| filters 语法 | 搜索 `["search","=","STEINS;GATE"]`；详情 `["id","=","v2002"]`（值是字符串）；角色按 VN `["vn","=",["id","=","v2002"]]`（值是**嵌套的 VN filter**） |
| 角色字段 | `vns.role`（main/primary/side/appears）、`vns.spoiler`、`image.url`；角色 API **不含声优**（在 VN 的 `va` 字段） |
| rating | 0-100 标度（本项目统一 0-10 展示 → 除以 10 保留 1 位） |
| 描述 | 含 BBCode（`[b]` 等），normalize 前用正则清洗 |
| 限流 | 文档"200 请求/5 分钟 + 1 秒执行/分钟" → 令牌桶 **40 rpm** |

## 二、实现

- `app/connectors/vndb/manifest.json` + `connector.py`，结构参考 Bangumi/萌娘百科，
  但 HTTP 层用 `http_post(json_body=...)`（复用 base 的 POST 助手，不用 GET 风格）。
- `search`：`POST /kana/vn` `["search","=",q]`，`sort=searchrank, results=10`，
  fields 含 id/title/alttitle/image.url/description/rating/developers/released/tags。
- `get_detail`：`POST /kana/vn` `["id","=",id]` 拿详情 + `POST /kana/character`
  `["vn","=",["id","=",id]]` 拿角色，失败角色不阻塞详情。
- 角色归一化：`vns.role` → 角色墙 `relation`（`main→主角, primary→主要角色,
  side→配角, appears→登场`，与 Bangumi 中文 relation 一致）；`actors` 留空
  （角色 API 不含声优）；复用 `base.normalize_characters`。
- 描述 BBCode 清洗、rating 0-100→0-10。

## 三、联合检索

VNDB 经 `registry.discover()` 自动注册，federated search 复用现有降级机制
（单源失败只记 `errors`，不阻断其它源）；前端来源角标复用 `r.source` 文本
（"vndb"），无需改前端。

## 四、顺带修复一个真实 bug（第三源暴露）：Connector 缓存跨源污染

所有 Connector 共用同一张 `connector_cache` 表，且 key 前缀相同
（`search:{q}` / `detail:{id}`）——前两个源没暴露（bangumi/moegirl 查询词
不重叠时各自覆盖），VNDB 一接入，vndb 读到了 moegirl 的 `search:命运石之门`
缓存页 → external_id 变空。修复：`RequestCache` 加 `namespace` 参数，key
内部前缀 `f"{namespace}:{key}"`；三个 Connector 都传 `namespace=self.name`。

## 五、测试与实测

- **pytest +13**（test_vndb：BBCode 清洗/角色归一化、search 真实结构映射
  （rating 90.2→9.0）、POST body 断言、API 错误/限流、detail 含角色/缺失/角色
  失败降级、normalize、discover 注册、**缓存 namespace 隔离**）。
- **实测（真实 API，直连）**：
  - `search("Steins;Gate")` → 10 条（STEINS;GATE v2002 rating 9.0、STEINS;GATE 0
    8.1…）；
  - `get_detail("v2002")` → STEINS;GATE，rating 9.0，**17 个角色**
    （Makise Kurisu 主要角色、Shiina Mayuri 主角…含图片）；
  - **真实联合检索三源同时工作**："Steins;Gate" → bangumi 10 / moegirl 10 /
    vndb 10，`errors:{}`；"命运石之门" → bangumi 10 / moegirl 10 / vndb 4，
    `errors:{}`；vndb 正确返回 v2002 等（缓存命名空间修复后无空 id）。
- 全量 pytest **305 passed**（+12 vndb + 缓存命名空间），vitest 67、build 通过。
