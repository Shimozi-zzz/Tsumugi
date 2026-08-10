# 0045 · Work 模型世界轴列（P1，增量演进）

日期：2026-08-10
状态：已接受
基准：prompts/07_WORK_MODEL_AUDIT + 14_DATABASE_ARCHITECTURE + WORK_MODEL_DESIGN.md（已定案）
回档节点：`pre-refactor-2026-08-10`

## 一、范围

把"作品（Work）"从通用条目（Item）中泛化出**可查询的世界轴列**：`work_type`（作品类型）、
`alternative_title`（原名）、`release_date`（发行日期）。**只加列、不建新表、不推倒 Item**，
从 `raw_metadata` 幂等回填（只填 NULL，不覆盖用户值）。

**本轮明确不做**：Character/Series/Creator 实体表（P4）、Collection 独立（P2）、
Memory 素材扩展（P3）、作品类型驱动的 AI 推断。

## 二、核心决策

1. **单表演进**：保留 `items` 作为 Work Core（统一容器），**不新建 works 表**；`type`
   （note/image/external_ref）表示内容形态，`work_type` 表示作品类型，二者正交。
2. **枚举 6 值**：`anime/manga/game/galgame/novel/other`——**galgame 与 visual_novel
   不分开**（社区语境二者高度重叠，galgame 为常见说法，避免枚举碎片化，WORK_MODEL_DESIGN 定案）。
3. **只落 3 列**：`creator`/`series_name` 等**不落列**（自判）——无数据源填充（纯空列属
   提前设计），且 P4 实体化时以 Character/Series/Creator 表 + FK 承载，现在落列是会被
   替换的一次性设计。
4. **幂等回填，只填 NULL**：`backfill_work_columns(engine)` 启动时调用，遍历外部条目从
   `raw_metadata.detail.metadata` 提炼；bangumi `type→work_type`（2→anime/4→game/1→manga/
   其余→other）、`original_name→alternative_title`、`date→release_date`；**不覆盖用户已填值**；
   重复运行只补缺口。
5. **收藏入库即提炼**：`_save_external_sync` 写 raw_metadata 时同步 `apply_work_columns`
   （同样只填 NULL）。
6. **手动编辑**：详情页"外部世界"区内联编辑 `work_type`（`PATCH /items/{id}/work`，枚举
   校验、空串=清除）；原名/发行日期本轮只读展示（列优先，回退 meta）。

## 三、与既有决策的关系

- 对 ADR 0016（角色/资料内嵌 raw_metadata）：**不改动**，raw_metadata 保留为完整兜底，
  新列只是其可查询提炼；
- 对 ADR 0026（多来源各收藏一份）：**正交**，work_type 不跨源合并，按条目各自归属；
- 对 ADR 0010/0025（ensure_schema 幂等迁移 + 只填 NULL 回填）：**同款模式**沿用。

## 四、接口/UI 影响

- `GET /items?work_type=anime` 结构化筛选（Level 2 检索台能力前置）；
- `ItemOut`/`ItemDetailOut` 新增 work_type/alternative_title/release_date；
- 详情页 InfoTable 显示 类型/原名/发行日期（列优先）；外部作品提供类型内联编辑；
- 图书馆视图按作品类型筛选 chips（有该类型数据时显示）；
- 命令面板条目关键词含 work_type（可搜"galgame"直达条目）。

## 五、测试与实测

- pytest **419 passed**（+9 `test_work_model.py`：bangumi 映射/type 变体/无类型源空、
  回填幂等/不覆盖用户值/本地不动/ensure_schema 加列/筛选与详情/PATCH 编辑与枚举校验），
  覆盖率 87.06%。
- vitest **204 passed**（+6：itemInfoRows 列优先、详情页内联编辑 PATCH、本地笔记无下拉、
  图书馆类型筛选 chips、命令面板 work_type 关键词）。
- 实测见简报（真实库 63 条回填 work_type/原名/发行 + UI 截图）。
