# 0018 · 安利卡生成（分享卡片）

日期：2026-08-06
状态：已接受

## 背景

给一个 Item 生成一张可导出的"安利卡"（封面 + 标题 + 我的评分 + 一句短评），
ACG 圈子常见的分享形式。复用 Stats 面板已验证的"手写 SVG"技术路线，不引入
图表/Canvas 库；前端渲染 SVG，浏览器端转 PNG，后端不参与生成。

## 一、卡片内容与生成方式

### 内容
- **封面**：本地已缓存图（`file_path` → `/static`，同源）优先，其次外部
  `image_url`；转成 data URL 内联进 SVG 再导出。
- **标题**：原样，SVG 内按每行 16 字断行，最多 2 行。
- **我的评分**：取 `ItemDetailOut.my_rating`（**评分聚合值**，非单条 Review
  评分）；为 null 时**整块省略评分区**（分享向，不硬凑"暂无评分"占位）。
- **短评**：见下节。

### 生成方式（手写 SVG）
- `frontend/src/shareCard.js`（纯函数，可测试）：
  - `buildShareCardSvg` 输出 640×800 竖版 SVG：主题渐变背景 + 环境光晕 +
    TSUMUGI·安利 眉题 + 圆角封面（阴影）+ 标题 + 来源角标 + 评分 + 短评 +
    "from Tsumugi" 页脚；
  - **取色复用主题 CSS 变量**（`readCssVar`/`readThemeColors` 读取 --bg/--panel/
    --accent/--text 等），导出时用**具体色值内联**（CSS 变量在独立 SVG 里不
    生效），保证卡片与当前主题视觉一致且可导出；不引入新配色体系。
- 导出：`svgStringToPngBlob`（Blob → Image → Canvas 2x → toBlob PNG）+
  `downloadSvgAsPng`。**封面必须先转 data URL 内联**（`imageUrlToDataUrl`），
  否则跨域图会污染 Canvas（taint）导致无法导出。本地 /static 封面同源可正常
  内联；远程无 CORS 的封面取不到 data URL 时**退化为占位封面**（柔和渐变），
  卡片仍可导出。

## 二、短评来源与 Spoiler 处理（复用既有约定）

### 选取逻辑（决策）
取**最新一条非 spoiler 的 Review 内容**（`selectQuote`）：

- `fetchItemReviews` 已时间倒序，[0] 即最新，取它而非"第一条/手动选择"，
  理由是短评应反映**最近的评价倾向**（追更后更接近此刻的感受），且实现
  无交互成本；
- 内容清洗：折叠空白、截断到 60 字加省略号（`cleanQuote`）。

### Spoiler 处理（强制，不能忽略）
- **spoilered Review 绝不进安利卡**——比 RAG 检索更严格：安利卡要分享到
  应用外部，剧透一旦发出无法收回；
- 全部 Review 都 spoiler → 短评区显示"作者选择不剧透"，**不退回用 spoiler
  内容**；
- 完全没有 Review → 短评区整块省略（不显示任何占位文案）。

## 三、入口

- Item 详情弹层（`ItemDetailModal`，saved 时）加"生成安利卡"按钮；
- `ShareCardModal`：拉取 item detail（my_rating/file_path/image_url）+
  reviews（quote 选取）→ 生成 SVG 实时预览 → "下载图片 (PNG)"。

## 四、后端改动

- `ItemDetailOut` 补 `file_path`（本地缓存封面，供安利卡拼 /static 同源
  URL）；`item_detail` 路由返回。无其它后端改动。

## 五、测试与实测

- **Vitest +19**（share-card.test.jsx）：短评选取（最新非 spoiler / 跳过
  spoiler / 全 spoiler→null / 无 review→null）、清洗截断、卡片组合（有/无
  评分、有/无短评、spoiler 过滤后"作者选择不剧透"、XML 转义、占位/内联
  封面）、ShareCardModal 渲染 + 下载触发。全量 vitest 34 passed。
- pytest **266 passed**（file_path 字段断言）；`npm run build` 通过。
- **实测（真实链路）**：收藏真实 Bangumi 作品 → 加 1 条 spoiler + 1 条
  非 spoiler review → item detail `my_rating=8.5`（8 与 9 的均值）→ 用真实
  `buildShareCardSvg` 生成卡片：
  - 短评正确选中**非 spoiler** 那条（"非剧透短评：天才们的恋爱头脑战…"），
    剧透内容未出现；
  - 封面经 Clash 代理取到真实 lain.bgm.tv 封面并以 data URL 内联；
  - 用 headless Edge 把该 SVG 光栅化为 **PNG（640×800，签名合法）**——
    证明"导出图片"端到端可行。
