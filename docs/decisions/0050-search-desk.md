# 0050 · 检索台：个人全文检索（P6）

日期：2026-08-10
状态：已接受
基准：docs/product-brief-v1.1.md（九节检索台目标状态 + 修正二"世界/我的两套入口合并"）+
PROJECT_AUDIT P6

## 一、范围

把问答检索台升级为**统一检索台**：提交查询后同时展示 **我的检索**（个人全文匹配：
作品/笔记、书评、记忆）、**外部检索**（Connector 联合检索，已有）、**AI 回答**
（本地 RAG，已有）——兑现 v1.1 修正二标注的目标状态（"世界检索与我的检索合并入口"）。

**本轮明确不做**：L4 个人记忆理解（AI 总结，属 AI 增强）、把 RAG 语义检索接入个人搜索
（Phase G）、结构化查询命令语言（"我收藏的 galgame"已由 P1/P2 的 work_type/collection_status
筛选覆盖，检索台内不另造语法）。

## 二、核心决策

1. **个人全文检索接口** `GET /api/search/my?q=&limit=`：对 Item(title/content)、
   Review(title/content)、Memory(summary) 做 **SQLite LIKE 子串匹配**（`ilike` 大小写不敏感），
   返回 `{ works, reviews, memories }` 三组（个人轴内容）。个人库规模下 LIKE 足够，
   不需要为此上向量检索；RAG 语义检索属 Phase G。
2. **记忆文本筛选**：`/memories` 与 `query_memories` 增 `search` 参数（summary 子串匹配），
   记忆回廊可按文本筛。
3. **检索台整合（前端）**：问答提交时并行调 `searchMy`，渲染"我的检索 ·「q」"块
   （作品→详情、书评→只读弹层、记忆→只读弹层）；`hasContent` 扩展为"提交过检索即有
   内容"，使检索台从神殿首页切换到内容分支（即使无命中也显示"没有匹配的我的记录"）。
4. **只读弹层复用**：命中的书评/记忆点击走 MemoryReviewModal（P3 泛化版本），与时间轴/
   往年今日一致。

## 三、接口

- `GET /api/search/my?q=&limit=` → `{ works: [ItemOut], reviews: [ReviewOut], memories: [MemoryOut] }`
- `GET /api/memories?search=`（summary 子串筛选）

## 四、测试与实测

- pytest **418 passed**（+2：search/my 三组命中/空查询/无命中、memories?search 文本筛选）。
- vitest **212 passed**（+2：提交查询展示我的检索含作品/书评/记忆、无命中空提示）。
- 实测见简报（真实库检索"命运石之门/孤独"等命中个人内容，截图）。
