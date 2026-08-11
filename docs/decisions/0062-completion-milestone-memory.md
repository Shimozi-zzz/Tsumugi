# 0062 · 完成时刻 milestone Memory 自动采集（Phase D）

日期：2026-08-11
状态：已接受
基准：docs/product-brief-v1.1.md 二十三节 Phase D（完成时刻）+ 0046（收藏时刻）+ 0047
（milestone 直接记忆已支持）+ AGENTS.md（Core 无 AI 也完整）

## 一、范围

用户把作品收藏状态**迁移到「看完」**时，自动生成一条 `source_type=milestone` 的
Memory（"这一天，我把《{title}》看完了"），无需手写任何文字。这是"让 Memory 真正
独立于 Review"的第一步：不是新的数据结构，而是**在真实完成时刻自动留痕**。

**本轮明确不做**：历史回填（34 条既有"看完"不批量造记忆，沿用 0046"不为历史造
收藏 Memory"先例）；"重新打开作品"自动采集（需最后打开时间追踪，易噪音，后续单独
排期）；改变往年今日对 milestone 的语义（ADR 0047 仍只对 review 触发）；Phase F /
RAG / AI / Ollama 一律不动。

## 二、核心决策

1. **触发点 = 真实状态迁移**：只在 `set_collection`（用户 PATCH 收藏状态）内部检测
   `未看完 → 看完` 迁移。导入（`on_collect`）与启动回填（`backfill_collections`）不走
   `set_collection`，天然不会为历史数据造记忆。
2. **幂等语义**：同一次「看完」重复保存不重复（old == 看完 无迁移）；`看完 → 其它 →
   再次看完` 视为新的真实完成事件，可再生成一条（每次完成都值得被记住）。
3. **轻量创建，不写向量**：与收藏时刻（0046）同款模式——完成时刻不被可选 embedding
   阻塞（Core 无 AI 也完整）。若需参与个人语义检索，由启动时既有 `backfill_memory_vectors`
   （ADR 0051，source_type=memory）幂等补向量，创建路径零 RAG 依赖。
4. **字段**：`source_type=milestone`、`source_ref=NULL`（无主记录）、`occurred_at=实际
   完成时间`、summary=`这一天，我把《{title}》看完了`、emotion 留空。
5. **可删除**：milestone 属于 `DIRECT_MEMORY_TYPES`，`delete_direct_memory`（0047）可删，
   误触可回滚。

## 三、接口 / UI 影响

- 后端：`app/collections.py` 新增 `create_completion_memory` + `set_collection` 迁移钩子；
  `PATCH /items/{id}/collection` 行为不变（返回结构同前）。
- 前端：**零改动**（时间轴已渲染"里程碑·完成了"徽标，P3 已支持）。
- 无数据库表变更、无既有数据修改。

## 四、测试与实测

- pytest：+5（看完迁移生成摘要/occurred_at、同状态重存幂等、看完↔其它↔看完=两条、
  非看完不触发、回填不触发）+1 API 层验证；全量 420+6 需跑通。
- vitest：无前端改动，全量回归即可。

## 五、与既有决策的关系

- 0046（收藏时刻）："带进图书馆"的自动记忆；0062 是"读完它"的自动记忆——两者构成
  「我的轴」的自然节奏（收藏 → 完成）。
- 0047（milestone 直接记忆）：0062 复用其类型与展示/删除机制，但创建是**系统自动**，
  不经过手动 composer，故不写向量（P7 语义由 backfill 兜底，见决策 3）。
- 0051（Memory 进语义检索）：不新增/修改任何 RAG 代码，行为由既有 backfill 承接。
