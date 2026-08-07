# 0022 · Bangumi 收藏批量导入（OAuth 授权 + 批量拉取）

日期：2026-08-06
状态：已接受

## 背景

用户在设置页完成 Bangumi OAuth 授权后，一键把完整收藏批量导入本地图书馆，
免去逐部手动搜索收藏。在既有 `BangumiConnector`（search/get_detail/normalize
+ 令牌桶 + 代理）基础上扩展，不另起一套调用逻辑。

## 一、OAuth 授权流程与 Token 存储

### 流程
- 设置页填 client_id/client_secret → 写入 `.env`（`BANGUMI_CLIENT_ID`/
  `BANGUMI_CLIENT_SECRET`，复用 `providers.write_secret_to_env`，**不落库明文**）；
- `GET /api/bangumi/oauth/authorize-url` 构造 `https://bgm.tv/oauth/authorize`
  跳转链接（含随机 state，回调校验防 CSRF），前端 `window.open`；
- 回调 `GET /api/bangumi/oauth/callback?code=&state=` → `exchange_code` 用
  code 换 token（POST `https://bgm.tv/oauth/access_token`），返回可关闭的 HTML 页；
- 前端轮询 `/api/bangumi/oauth/status` 直到 connected，显示"已连接 + 用户 id"。

### Token 存储方案（决策）
- client_id/secret：环境变量占位符（静态、用户提供）→ 存 .env，DB 不落明文
  ——与 Provider/Connector 完全一致；
- access_token/refresh_token：**动态获取的密钥，无法用环境变量占位符表达**，
  存 `data/bangumi_tokens.json`（gitignored，与 .env 同一信任模型：DB 不落明文）。
  不引入加密库（个人本地应用，文件级隔离 + 0o600 足够；未来多用户/公网再升级）。
- **过期/刷新**：`get_valid_access_token` 临近过期（<60s 余量）自动
  `refresh_access_token`；刷新失败抛 `NeedsReauthError`，接口返回 401 +
  "请重新授权"，前端 toast 明确提示，不静默失败。
- **SSRF**：token 兑换/刷新端点与收藏端点都过 `check_ssrf_target`（bgm.tv 公网
  正常通过）；回调地址是本机后端自身（入站），不构成出站 SSRF 面。

## 二、批量拉取收藏

- `BangumiConnector.get_collections(access_token, offset, limit, subject_type)`
  复用 `_request`（令牌桶限流 + 代理 + Bearer 头），分页 `limit=30`；
- `app/bangumi_import.py`：后台线程跑（daemon，无任务队列框架），job 状态
  （total/current/imported/skipped/failed/failures）可轮询
  `GET /api/bangumi/import/status`；前端进度条 + "已导入 X/Y + %"。
- 单条失败不阻塞整体（记入 failures，保留最近 20 条原因）。

## 三、数据映射（核心设计）

### 收藏条目 → Item
复用 `ingest_external`（幂等，source+external_id 去重）——收藏接口的
`subject` 内嵌轻量摘要（title/name_cn/short_summary/images/tags），批量导入
直接用它建 Item，不重复调 search/detail。

### 追番状态 + Bangumi 个人评分 → Review（决策）
- 为每条收藏自动创建一条 **Review**：`rating = Bangumi 个人评分`（0 视为未评分
  → `rating=None`），`status` 映射 Bangumi 收藏类型：
  `1→想看 2→看完 3→在看 4→搁置 5→弃坑`（与现有 Review 状态枚举一致）；
  `content=""`（**不产生向量**，避免几百条平凡文本全量 embedding）、
  `title="从 Bangumi 导入"`。
- **Review 增加 `source` 列**（`bangumi_collection`）：去重用
  （同 item 同 source 只一条），重复导入**原地更新** rating/status（反映最新
  状态），不产生重复 Review。这也是"我的平均分"（get_my_rating）能正确聚合
  的前提。
- 为什么不丢：评分/追番状态是收藏的核心价值，丢弃就白导入了；映射到现有
  Review 模型无需新表，且自动 Review 可被用户编辑补充。

### 去重
- Item：`ingest_external` 幂等（已有条目直接返回，不重建）；
- Review：`Review.source == "bangumi_collection"` 查询，命中则更新。

### 角色信息分批策略（本轮技术权衡的核心）
- **批量导入时不拉角色详情**（几百条逐条 get_detail+characters 会请求量爆炸、
  触发限流/超时），只存收藏接口自带的基础信息；
- 角色**按需懒加载补充**：`GET /api/characters` 时调
  `backfill_bangumi_details(limit=20)`——给缺 raw_metadata.detail 的 bangumi
  条目补详情（受令牌桶限流约束，单次最多 20 条，失败跳过），多次查看角色墙
  逐步补齐。不用任务队列，简单分批即可（任务明确允许）。

## 四、前端（设置页新增 "Bangumi" tab）

- OAuth 引导（开发者后台链接 + 回调地址展示 + client_id/secret 表单）、
  连接状态（已连接 + 用户 id + 断开）、批量导入按钮 + 进度条 + 结果摘要
  （导入 N / 跳过 M / 失败 K + 原因），复用 toast 反馈。

## 五、测试与实测

- **pytest +20**（test_bangumi_oauth：凭证写 .env/空校验/缺凭证报错、authorize
  URL、code 兑换/state 校验/自动刷新/刷新失败→重新授权/未连接/断开；
  test_bangumi_import：状态评分映射（含 type 全表/rate=0）、去重更新、
  分页导入 2 页、重复导入不重复、单条失败不中断、角色懒补与已补跳过）。
- **vitest +3**（BangumiPanel：未配置引导 / 已连接状态 / 导入轮询进度摘要）。
- **实测（真实链路边界如实说明）**：
  - 真实公开用户收藏 API 已通过代理抓到 **508 条**（type 分布 2/1/3/4/5，
    rate 0-10）——结构确认，映射输入真实；
  - 用其中 12 条**真实收藏数据**跑通完整导入映射（真实标题 + 状态/评分正确
    转成 Review，如"阿基拉→看完★9"、"电影 吉伊卡哇→想看"，未评分→null），
    验证后清理；
  - `get_collections` 用无效 token → **401 ConnectorError**（诚实：真实收藏
    需要真实 OAuth token）；
  - **真实 OAuth 卡在凭证一步**：需要用户先在 Bangumi 开发者后台注册应用拿
    client_id/secret（本机无法代为注册）。授权/兑换/刷新/过期处理由 mock 测试
    覆盖；拿到凭证后填入设置页即可走完整真实流程。
  - SSRF：token/收藏端点通过 `check_ssrf_target`。
- 全量 pytest **291 passed**（+20）、vitest **67 passed**（+3）、build 通过。

## 六、真实端到端验证（追加，用户注册真实 Bangumi 应用 + 授权）

用户提供了真实 App ID/Secret 并在开发者后台登记回调地址、勾选"收藏-READ"，
完成了首次**真实 OAuth + 批量导入**：

### 授权（一次通过，过程中修掉 1 个真实 bug）
- 写入凭证 → `config_configured:true` → 生成授权链接（经 Clash 代理验证
  authorize 页 200）→ 浏览器完成登录授权 → 回调换 token 成功，
  `connected:true, user_id:1051338`。
- **bug ①（status 500）**：Bangumi token 返回的 `user_id` 是**整数**
  `1051338`，而 `BangumiOAuthStatusOut.user_id` 声明为 `Optional[str]` →
  status 接口 500。修复：route 里 `str(user_id)` 归一化。
- **bug ②（收藏 404）**：`get_collections` 用 `/v0/users/-/collections`
  （`-` 表示当前用户）→ **404**。真实 API 需要真实用户名。修复：新增
  `_resolve_username` 调 `/v0/me`（复用代理 + Bearer）拿 username 并缓存到
  token 文件，再用 `/v0/users/{username}/collections`。

### 批量导入（真实 57 条）
- **57/57 全部成功，耗时 17.6s，0 失败，未触发限流**（57 条 < 令牌桶 20rpm
  窗口内的请求预算）。
- 抽查真实映射：`CLANNAD→看完★10`、`进击的巨人 第三季→看完★9`、
  `BanG Dream! Ave Mujica→看完★6`、`Silent Witch→想看(未评分→null)`、`钢炼→
  想看(null)` —— 标题/状态/评分映射全部正确。
- **bug ③（重复导入计数错误，非数据错误）**：第二次导入数据层**无重复**
  （57 items/57 reviews/0 重复 external_id，ingest_external 幂等 + review
  upsert 生效），但 job 计数把"已存在"误标为 `imported`、`skipped` 恒 0。
  修复：`_import_page` 先查 `(source, external_id)` 是否已存在，存在记
  `skipped` 并只更新 review；再次导入报 **imported 0 / skipped 57**。

### 角色墙懒加载（真实 57 条基数）
- 初版把补详情放在 `list_characters` **同步等待** → 受 20rpm 限流 + 每条
  详情 2 个请求约束，一次响应阻塞 **~119s**（体验不可接受）。
- 修复：`backfill_async` 后台单飞线程（已在跑则不重复启动），响应**立即返回
  当前已聚合角色**；实测角色墙 **0.23s** 返回，后台逐步补齐（41→50 条详情
  /70s，随后续查看继续填）。无需任务队列框架。
- 真实数据下角色墙返回 1169 个角色（随详情补齐还会增长），无卡顿/报错。
