# 0048 · Character 角色实体化（P4）

日期：2026-08-10
状态：已接受
基准：prompts/07_WORK_MODEL_AUDIT（Character 独立实体/角色 Memory）+ 14_DATABASE_ARCHITECTURE（Character 实体）+ PROJECT_AUDIT P4

## 一、范围

把角色从 raw_metadata 内嵌提炼为**独立实体表** `characters` + `character_works` 多对多关联，
角色墙 / 声优图谱改从表读取（不再每次全表扫 JSON）。

**本轮明确不做**：Series / Creator 实体化（当前无任何数据源提供 series/creator 字段，
建空表属提前设计，等有数据来源再建）；Memory↔角色关联（characters 实体已就绪，关联只需
Memory 加一列 FK，待 Memory Composer 05 号文档排期时连同角色选择 UI 一起做）。

## 二、核心决策

1. **建表（推倒 ADR 0016 的角色部分）**：ADR 0016 当时选择"角色不建独立表（raw_metadata
   内嵌 + 聚合实时扫描）"。P4 **有意推翻**——理由：① 实时扫描所有条目 JSON 无法用索引、
   条目多了会慢；② 角色作为实体后，未来可做角色档案页、Memory↔角色、按角色检索；
   `raw_metadata` **仍保留为权威来源**，`characters` 表是派生索引（同步重建，不删旧数据）。
2. **表结构**：`characters`（id/source/external_id/name/image_url/relation/summary/actors
   [JSON]）+ `character_works`（character_id + item_id 多对多）。
3. **去重键**：`(source, external_id)` 优先；无 id 时 `(source, name)`。跨作品聚合后
   Character.works 含多个作品。
4. **relation 合并**：主角优先（同一角色在 A 是主角、B 是配角 → 记主角）。
5. **同步策略**：`sync_characters(item, db)` 重建单作品索引（断旧链接 → upsert → 建链接
   → 删孤儿）；收藏入库（`_save_external_sync`）与详情刷新时调用；`backfill_characters(engine)`
   启动时全量幂等重建。
6. **接口不变**：`GET /characters` 与 `GET /voice-relations` 返回结构与前端一致（角色墙/
   声优图谱前端**零改动**），仅数据源从"扫 JSON"改为"查表"。

## 三、与既有决策的关系

- 对 ADR 0016（角色 raw_metadata 内嵌 + 实时聚合）：**有意推翻角色部分**，raw_metadata
  保留兜底（详情页仍从它展示单作品角色）；
- 对 ADR 0032（声优邻域图谱）：数据源从 JSON 扫描改为表，输出结构不变。

## 四、测试与实测

- pytest **416 passed**（重写 `test_characters.py` 4 例：去重/主角优先合并/跨作品 works/
  重建删旧链接删孤儿/回填/API 走表 + `test_voice_relations.py` 适配 5 例）。
- vitest **207 passed**（角色墙/声优图谱前端零改动，接口形状未变）；build 通过。
- 实测见简报（真实库启动回填 characters 表 + 角色墙/声优图谱仍正常，截图）。
