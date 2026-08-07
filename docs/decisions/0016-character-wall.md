# 0016 · 角色图鉴：get_detail 接入前端 + 角色墙聚合

日期：2026-08-06
状态：已接受

## 背景

上一轮已把 Bangumi/萌娘百科的 `get_detail` 在后端验证通过（经本地 Clash
代理）。本轮把详情接到前端：点开作品详情看角色，并新增"角色墙"跨作品
聚合展示。核心前提：**角色数据必须先落库**，前端聚合才有数据源。

## 一、raw_metadata 角色数据结构（关键决策）

### 实测确认（决定字段来源）

Bangumi `GET /v0/subjects/{id}` **不含角色**（keys 见实测），角色在独立
端点 `GET /v0/subjects/{id}/characters`（27 个，字段 id/name/images/
relation/summary/actors/type）。因此 get_detail 需要**多拉一次角色端点**。
萌娘百科 get_detail 无角色数据（返回分类/简介/封面），按"返回什么展示
什么"原则，角色为空。

### 统一角色字段（base.normalize_characters）

```
{id, name, image_url, relation, summary, actors:[声优名]}
```

- 只保留有名字的角色；无 id 也保留（同名可作聚合键兜底）；
- `actors` 取前 5 个声优名（Bangumi actors 可能为空）；
- Bangumi 角色图在 `images` dict 里，先抽 `large/medium/grid/small` 再走
  统一规范化。

### raw_metadata 统一结构（收藏入库时写入）

```
raw_metadata = {
  "source": ...,
  "detail": {
    "title": ..., "description": ..., "image_url": ...,
    "metadata": {rating, tags, date, characters, ...}  # ItemDetail.metadata 原样
  }
}
```

**选择说明**：
- 存**归一化的 ItemDetail**（而非原始 API JSON）：前端跨数据源统一读取
  `raw_metadata.detail.metadata.characters`，不感知各源原始结构差异；
- 保留 `metadata` 原样（含 rating/tags/date/characters），评分在
  `get_public_rating` 里的读取（reviews.py）补了兼容：新结构
  `detail.metadata.rating`，旧结构顶层 `rating`（兼容此前存原始 subject
  的旧条目）；
- 不做"角色"独立数据库表——角色作为 `raw_metadata` 内嵌数据，聚合时实时
  扫描（个人库量级够用），避免过度设计（任务明确要求）。

## 二、收藏入库时机（补上持久化）

原 `_save_external_sync` **只存搜索级信息、raw_metadata=None**。本轮改为：
- 若 Connector `manifest.capabilities` 含 `get_detail`，收藏时**顺带拉一次
  详情**，构建上述 raw_metadata 写入（角色墙数据前提）；
- 详情字段（title/description/image_url/tags）优先于搜索级；
- 详情失败（ConnectorError）→ **降级**为搜索级信息，不阻塞收藏；
- 幂等重收藏：raw_metadata 有内容则覆盖（旧条目无 raw_metadata 的，重收藏
  后回填详情）；
- 幂等逻辑在 ingest_external 外层处理（ingest_external 幂等命中提前 return，
  不重写 raw_metadata）。

## 三、前端

- **详情弹层 `ItemDetailModal.jsx`**：封面大图 / 标题 / 来源角标 / 评分 /
  简介 / 标签 / 登场角色网格（立绘+名字+关系），未收藏时可"收藏入库"。
- **角色墙 `CharacterWall.jsx` + 新导航项「角色」**：跨收藏作品聚合角色
  （卡片：立绘+名字+来源+作品数）；点击角色 → 显示"出自作品"（点作品回
  详情）；空态引导去搜索收藏。
- **入口**：
  - 联合搜索结果行：标题/详情按钮 → `GET /api/external/detail`（live）；
  - 已收藏作品卡片：点击卡片 → `GET /api/items/{id}/detail`（读 raw_metadata）；
  - 角色墙点作品 → 打开对应已收藏条目详情。
- **新端点**：
  - `GET /api/characters`：扫描外部条目 raw_metadata 提取角色，按
    (source, char_id) 去重合并 works；
  - `GET /api/items/{id}/detail`：返回条目 + 提炼的 detail；
  - `GET /api/external/detail?source=&external_id=`：live get_detail。

## 权衡与局限

- **聚合实时扫描 vs 建表**：不建表，扫描全部外部条目提取（个人库量级
  可接受）；未来量大了再物化。
- **角色去重键 (source, id)**：同名角色跨源不合并（Bangumi 与萌娘百科的
  同名角色是不同实体），同源同名（无 id）合并。
- **萌娘百科无角色**：角色墙只有 Bangumi（及未来有 characters 的源）；
  萌娘百科的分类作为 tags 展示（`metadata.tags` 与 categories 同源，已过滤
  维护类）。
- **详情失败降级**：收藏不因详情失败而失败；角色拉取失败不阻塞 get_detail
  （Bangumi 实现里 characters 端点异常 → 空列表）。

## 测试

- `tests/test_connectors.py`：Bangumi get_detail 含角色（mock /characters，
  真实结构样例）、缓存路径、角色接口失败降级；
- `tests/test_characters.py`（+9）：收藏入库存 detail raw_metadata、详情失败
  降级、旧条目重收藏回填、`/api/characters` 跨作品聚合去重、live external
  detail、item detail 404；
- 前端 `characters.test.jsx`（+6）：角色墙渲染/点角色看作品/空态、详情弹层
  渲染/已收藏态/收藏按钮；
- 全量 pytest **244 passed**（+12，覆盖率 83.82%）；vitest 15 passed；
  `npm run build` 通过。

## 实测（真实链路，经本地 Clash 代理）

- 收藏真实 Bangumi 作品 `135218`（辉夜大小姐…恋爱头脑战~）→ 详情标题被
  get_detail 覆盖为真实标题、rating 7.2、**27 个角色**（四宫辉夜/白银御行/
  藤原千花 主角）写入 raw_metadata；
- `GET /api/characters` 聚合出 **27 个角色**，各带关联作品；
- live `GET /api/external/detail` 返回 27 角色；
- 收藏萌娘百科 `1399`（初音未来）→ 详情落库、分类过滤后作 tags
  （8月31日/M形刘海/VOCALOID角色/双马尾/发饰/处女座）、角色为空（源无角色）；
- 测试数据已清理（角色墙回到空）。
