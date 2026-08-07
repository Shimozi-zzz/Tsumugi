# 0017 · 待办清理：评分聚合 + UI 直接填 Key + Spoiler 检索过滤

日期：2026-08-06
状态：已接受

三条相互独立的小项，各自记录决策。

## 一、评分聚合（Review 系统遗留）

### 背景

一个 Item 可有多条 Review 各自打分，但"大众评分 vs 我的评分"只在单条
Review 上对比，没有聚合出"我总体怎么看这部作品"。

### 决策

- 新增 `reviews.get_my_rating(item_id)`：该 Item 下所有 Review 评分的
  **均值**（忽略未打分的），全部未打分返回 `None`。
- 暴露在 `GET /api/items/{id}/detail` 的 `ItemDetailOut.my_rating`，与公众
  评分 `rating` 并列。
- 前端：`ItemDetailModal` 显示"大众 ★x / 我的平均 ★y"；`ReviewPanel` 头部
  按已加载的 reviews 本地计算同样的均值（单条时自然等于该条；全部未打分
  显示"暂无评分"）。

### 边界

- 单条 Review：均值 = 该条评分（无需特判）；
- 含未打分 Review：只对已打分求均值；
- 全部未打分：`None`，前端显示"暂无评分"而非 0。

## 二、UI 直接填 Key（体验缺口）

### 背景

设置页此前只支持 `{ENV_VAR}` 占位符，用户须先手动改 .env；与"填完就生效"
直觉不符。安全约束：**密钥不落数据库明文**。

### 决策（沿用"占位符 / 直接填 key 并存"，复用坑位 #15 的"不落明文"边界）

- **输入分类**：`providers.classify_api_key_ref(ref)` 返回
  `None` / `"placeholder"` / `"plaintext"`：
  - 空 → None（Ollama 无需 key）；
  - `{ENV_VAR}` → placeholder（原样存 `api_key_ref`）；
  - 其它非空 → plaintext（真实 key）；畸形占位符（单边括号）拒绝。
- **明文落地**：`providers.persist_api_key_placeholder(name, key)` 把真实
  key 写入 `.env`（变量名 `TSUMUGI_API_KEY_{NAME}`，已 gitignore、UTF-8、
  保留其它行、替换同名变量），并同步 `os.environ`（运行时立即解析），
  返回 `{TSUMUGI_API_KEY_{NAME}}` 占位符引用**存库**。数据库里永远只有
  占位符引用，明文只存在于 .env（本就是密钥文件）。
- **测试连接**：临时配置时明文直接作为 `api_key`（不持久化）；占位符仍走
  环境变量解析。已保存配置永远走占位符。
- `.env` 写入路径做成模块级 `SECRET_ENV_PATH`，测试 monkeypatch 到临时目录，
  避免污染真实 .env。
- 前端提示文案更新：支持两种方式任选。

### 为什么选"写 .env"而非"加密单独存储"

项目已有 .env 作为密钥载体且被 gitignore、启动时由 pydantic-settings 加载，
写入它是零新增依赖、可读可维护的方案；加密单独存储需要新增密钥管理/解密
链路（代价大于收益）。`.env` 里的变量名（`TSUMUGI_API_KEY_*`）与用户手动
配置的变量（如 `DEEPSEEK_API_KEY`）不冲突；换 Provider 时各用自己的变量名，
互不干扰。

## 三、Spoiler 内容参与检索

### 背景

Review 的 `spoiler=true` 内容前端折叠展示，但 RAG 检索未区分，可能把剧透
直接带进回答。

### 决策：方案A — spoiler 内容完全不参与检索（推荐并实现）

理由：
- **用户意图是强信号**：用户主动勾选"含剧透"，说明不希望该内容被随意
  浮出（问答场景常随手看完，剧透被带出是最糟糕的体验）；
- 方案B（参与 + 标记）无法真正防剧透——标记只是提示，LLM 仍可能在回答里
  复述 spoiler 内容，防护不可靠且实现复杂（要在 prompt 动态标注 + 依赖
  LLM 自觉）；
- 个人知识库定位：检索结果不包含剧透是更安全的默认；用户仍可在书评面板
  里主动展开阅读自己的剧透内容。

### 实现

- `retrieval._retrieve` 在向量检索拿到 hits 后，批量查 `Review.spoiler==1`
  的 id（`_get_spoiler_review_ids`），把对应 review chunk 从结果里剔除，
  再走去重/排序/截断。只影响 review chunk，item 自身内容不受影响。
- 不做可开关参数（保持简单；如需放开再加）。

## 测试与验证

- pytest **265 passed**（本轮 +21：评分聚合 6 + spoiler 4 + key 分类/落地 5
  + key 路由 6 + my_rating 路由 1，覆盖率 85.06%）；vitest 15 passed；
  `npm run build` 通过。
- 三条各自实测见简报对应小节。
