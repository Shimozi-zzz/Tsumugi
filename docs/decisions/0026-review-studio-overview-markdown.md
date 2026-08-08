# 0026 · 书评工作室 Overview 信息丰富化 + Markdown 预览修复 + 多来源切换

日期：2026-08-08
状态：已接受

## 一、Markdown 预览 bug 根因与修复（先复现后修）

### 复现
在既有手写渲染器 `frontend/src/markdown.js` 上逐语法探测，复现两个真实 bug：

1. **行内代码被其它行内格式误处理**：`` `**不是加粗**` `` 渲染成
   `<code><strong>不是加粗</strong></code>`——代码内容里的 `**`/`*` 又被加粗/
   斜体规则处理了一遍。原因：`inline()` 是"正则链式 replace"，代码 ` ` ` 先被替换成
   `<code>…</code>`，随后 strong/em 正则在**结果**上继续匹配，命中 `<code>` 内部。
2. **粗体含斜体嵌套撕裂**：`**外层*内层*内容**` 渲染成
   `*<em>外层</em>内层<em>内容</em>*`。原因：strong 正则 `\*\*([^*]+)\*\*` 的
   `[^*]+` 不允许内容含 `*`，遇到内嵌斜体直接匹配失败，随后斜体正则把外层 `*`
   撕裂成两个孤立 em。

另补：有序列表 `1. xxx` 不渲染（当前只有无序列表）。

### 修复
`inline()` 改为**逐字符 tokenizer**（`RE_CODE/RE_TRIPLE/RE_BOLD/RE_EMPH/RE_DEL/
RE_LINK` 顺序匹配 + 递归处理内联内容）：
- 代码优先匹配、**不递归** → 代码内容保持字面，彻底隔离其它规则；
- 粗体递归处理内容 → `**外层*内层*内容**` 正确输出
  `<strong>外层<em>内层</em>内容</strong>`；
- 新增 `***强调***` 支持、有序列表（`1.` / `1)`）渲染为 `<ol>`。
- XSS 策略不变：先整体 escapeHtml 再 tokenize，链接仍仅 http(s)。

## 二、Overview 面板信息丰富化

### 完整简介
`ItemDetailOut` 新增 `reference_text`（已下载完整资料，ADR 0025），前端
`introText()` 优先取 `raw_metadata.detail.description`（完整简介），缺失时从
`reference_text` 的"# 作品简介"小节提取——不再只显示搜索级片段。

### 紧凑角色列表
新增 `CompactCharacters`：每角色一行（名字 + relation 角标），点击展开小传与
声优，替代 Archive 的缩略图网格（Overview 更紧凑、信息更全）。

## 三、多来源切换（数据模型确认与设计）

**现有数据模型是一个 Item 只挂单一 `source` + `external_id`**，不支持"一个 Item
关联多个来源"。按任务约束（不做完整合并去重），采用**简单方案**：

> 同一作品从不同来源各自收藏一份（如 Bangumi 中文名 + 萌娘百科同名页面），
> 通过**规范化标题匹配**在 Overview 里切换查看。

- 新增 `GET /items/{item_id}/related`：`_title_key()`（小写 + 去空格/全角标点/
  括号）匹配其它非本地来源的已收藏条目，返回兄弟列表（source/title/id/rating）。
- Review Studio Overview 顶部渲染来源 Tab（当前条目 + 兄弟），懒加载各来源
  detail（`fetchItemDetail`），切换查看各来源的简介/标签/评分/热度/角色。
- 已知边界：VNDB 英文名与 Bangumi 中文名通常不匹配 → 返回空列表（预期，不强行
  合并）；两个不同作品撞同名的低概率误配可接受。

## 四、"热门评论"可行性实测结论（先实测后实现）

逐源实测公开 API（2026-08-08）：

| 数据源 | 用户评论/短评文本 API | 实测证据 | 替代数据（公开可查） |
| --- | --- | --- | --- |
| Bangumi | ❌ 无 | `GET /v0/subjects/{id}/comments` → **404**；OpenAPI v0 无 comments 路由 | `rating`（rank/total/score + 各分数人数 `count` 分布）+ `collection`（wish/collect/doing/on_hold/dropped）——**实测 3154 可返回** |
| 萌娘百科 | ❌ 无 | `prop=revisions` → **action-notallowed**；pageviews REST → **404** | 页面元信息（length/最后编辑 touched）；如实标注"未公开评论/评分数据" |
| VNDB | ❌ 无 | kana API `fields: "reviews"` → **400 "Field 'reviews' not found"** | `rating` + `votecount`（投票数）——**实测可取** |

**结论：三源公开 API 均无"其他用户评论文本"接口**（评论区只在各自网站前端，
无 API）。因此本轮**不做评论展示**，改为展示各源确实公开的替代数据：

- connector 在 get_detail 时把分布数据写入 raw_metadata（bangumi 新增
  `rating_info`/`collection`，vndb 新增 `votecount`/`length`，moegirl 新增
  `touched`/`lastrevid`；既有 `rating` float 字段保持不变，兼容 `get_public_rating`）；
- `external_refs.extract_social_meta()` 提炼为 `ItemDetailOut.social`；
- Overview 渲染"热度 / 评分分布"块：Bangumi 评分分布条形图 + 收藏分布；VNDB
  评分 + 投票数；Moegirl 页面信息 + 明确标注无评论数据。历史条目需「刷新资料」
  重新拉取才带分布数据（无则显示提示）。

## 测试与实测

- 后端 pytest **345 passed**（+11：connector social 元数据、extract_social_meta、
  item_detail social/reference_text、related 跨来源匹配/标点归一化/404）；
  覆盖率 85.8%。
- 前端 vitest **88 passed**（+7：markdown 修复 5 例 + Overview 多来源/社交块 +
  无兄弟回退）；build 通过。
- **实测（真实 API + headless Chrome CDP 驱动真实 App）**：
  - Markdown 预览：真实浏览器输入 `## 标题 / **加粗** / *斜体* / `**代码**` /
    有序列表 / > 引用`，预览 HTML 正确输出 `<h2>`、`<strong>`、`<em>`、
    `<code>**代码**</code>`（**代码不再被加粗**）、`<ol>`、`<blockquote>`；
  - Overview：真实收藏 Bangumi「魔法少女小圆」+ 萌娘百科「魔法少女小圆」，
    Overview 出现 Bangumi/萌娘百科 双来源 Tab，切换后分别展示各自**完整简介**、
    评分、热度分布；Bangumi 显示"评分分布 · 13 人评分 + 收藏 看过 26…"，
    萌娘百科显示"页面长度 69035 · 最后编辑 2026-08-07（该数据源未公开评论/
    评分数据）"；`/items/{bangumi}/related` 双向命中 moegirl 兄弟。
