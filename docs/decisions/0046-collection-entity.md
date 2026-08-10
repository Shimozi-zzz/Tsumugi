# 0046 · Collection 收藏关系独立（P2）

日期：2026-08-10
状态：已接受
基准：prompts/07_WORK_MODEL_AUDIT（Personal Relation 第二层）+ 14_DATABASE_ARCHITECTURE（Collection 实体）+ PROJECT_AUDIT P2

## 一、范围

把"收藏状态"从 Review 中分离为独立的 **Collection 实体**（1:1 关联 items）：追番状态、
收藏时间、是否喜欢；收藏动作自动生成最轻 **Collection Memory**（"这一天，我把它带回了
图书馆"）。

**本轮不做**：收藏/重访记录的时间线细化、多用户维度（单机本地）、按收藏状态驱动的复杂
书架布局（后续 Library 体验再排）。

## 二、核心决策

1. **独立表（1:1）而非 items 加列**：`collections`（item_id 主键/FK、status、favorite、
   added_at）。理由：① 14 号数据库架构明确 Collection 是实体；② **我的轴与世界轴分离**
   ——P1 刚把世界轴列加到 items，收藏状态属于个人轴，放独立表避免 items 变成两轴混装；
   ③ 收藏时刻 Memory（source_type=collection, source_ref=item_id）与 collection 行天然
   对应；④ 未来重访记录等个人关系扩展自然。
2. **状态源迁移**：追番状态源从 Review 改为 **Collection**；前端状态分组列表（statusMap）
   改读 `GET /collections`；Bangumi 导入同时写 collection.status（Review 保留书评/评分职责）。
   历史"从 Bangumi 导入"Review 的 status 迁移到 collection，**书评不删除**。
3. **收藏时刻 Memory（仅新增收藏时）**：`on_collect` 确保 collection 行 + **首次收藏**生成
   `source_type=collection` 的最轻 Memory；re-save/重复导入不重复造。**历史回填不批量造
   收藏 Memory**——避免 59 条自动记忆污染记忆回廊，收藏时刻 Memory 只对"往后新增收藏"生效。
4. **幂等回填**：`backfill_collections(engine)` 启动时调用，为外部条目建 collection 行
   （status 从 Bangumi 导入 Review 迁移、added_at=item.created_at、favorite=0）；本地笔记
   不建；多次运行只补缺口。
5. **手动编辑**：详情页"我的记录"区内联编辑 收藏状态（下拉）/ 是否喜欢（toggle）；
   `PATCH /items/{id}/collection`（status 枚举校验、空串=清除）。

## 三、接口

- `PATCH /items/{id}/collection`（status/favorite）
- `GET /collections`（item_id→status 列表，前端 statusMap）
- `GET /items?collection_status=` 筛选（我的轴结构化筛选）
- `ItemOut` / `ItemDetailOut` 增 `collection_status / collected_at / favorite`；
  列表用 `selectinload(Item.collection)` 避免 N+1。

## 四、与既有决策的关系

- 对 ADR 0022（Bangumi 导入生成状态 Review）：Review 仍创建（承载 rating），但 status
  同步写 Collection；状态展示源切换；
- 对 ADR 0041（Memory 独立容器 source_type 预留 collection）：本轮正式启用该来源类型；
- 对 ADR 0045（世界轴列）：两者正交，一个在 items（世界），一个在 collections（我的）。

## 五、测试与实测

- pytest **426 passed**（+7 `test_collections.py`：建表迁移/回填迁移 status 幂等且不造
  收藏 Memory/本地不动/on_collect 首次建行+Memory 且重复不造/set 校验/PATCH+筛选+detail/
  collections 映射），覆盖率 87.27%。
- vitest **206 passed**（+2：我的记录区收藏状态/喜欢内联编辑 PATCH、本地笔记无收藏编辑区；
  状态分组列表改读 collections 后主从/分组测试仍绿）。
- 实测见简报（真实库回填 collections + 详情页我的记录编辑 + 状态分组仍按收藏状态分组）。
