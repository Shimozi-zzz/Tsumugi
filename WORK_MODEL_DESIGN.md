# WORK_MODEL_DESIGN.md — Tsumugi 作品模型（Work Model）设计

> 阶段：P1 · Work 模型泛化（设计文档，**未改代码 / 未动数据层**）
> 依据：prompts/07_WORK_MODEL_AUDIT.md + 14_DATABASE_ARCHITECTURE.md + PROJECT_AUDIT_REPORT P1
> 状态：**待人工确认后再实施迁移**

---

## 一、核心实体设计

### 1.1 总原则：统一 Work Core，单表演进，不推倒 Item

- 保留 `items` 表作为 **Work Core**（作品/条目统一容器），**不新建 works 表**；
- `type`（note/image/external_ref）继续表示**内容形态**，新增 `work_type` 表示**作品类型**，
  两者正交；
- 世界轴"可查询标量"落为 `items` 新列，从 `raw_metadata` 幂等提炼回填；
- `raw_metadata` JSON 保留为完整原始数据兜底（不删，避免破坏 ADR 0016/0026 的既有消费方）；
- Character / Series / Creator **独立实体表推迟到 P4**，本设计不建新表（避免 P1 引入 P4 复杂度）。

### 1.2 Work（items）新增字段

| 字段 | 类型 | 说明 | P1 回填来源 |
| --- | --- | --- | --- |
| `work_type` | VARCHAR(20) | 作品类型：`anime/manga/game/galgame/visual_novel/novel/other`；note/image 为 NULL | bangumi metadata.type 映射 |
| `alternative_title` | VARCHAR(255) | 原名/别名（用于多来源匹配 ADR 0026、显示） | bangumi original_name |
| `release_date` | VARCHAR(20) | 发行日期（保留字符串，按需取年份） | bangumi date |
| `creator` | VARCHAR(255) | 主要创作者（原作/监督/脚本） | 暂无（connector 未拉 staff，待补；用户可手填） |
| `series_name` | VARCHAR(255) | 所属系列名（P4 将升级为 series 表 FK） | 暂无（当前数据无 series） |

> 取舍：`publisher`、`original_language` 等暂不落列——当前数据源无值、价值低，避免过度设计；
> 未来需要时按"新列 + 幂等回填"同一模式追加。

### 1.3 work_type 枚举（07 文档对齐）

```
anime / manga / game / galgame / visual_novel / novel / other
```

- `galgame` 与 `visual_novel` 分开列（用户可一眼区分）；若认为重复，可并归 game，P1 先按
  7 值实现；
- bangumi `type` 映射：`2→anime, 4→game, 1→manga, 3→other(音乐), 6→other(三次元), 其余→other`；
- moegirl / vndb 无类型信息 → 回填留 NULL（不瞎猜），由用户在 UI 手选；
- 映射到 `other` 的不确定性：bangumi type=1 既含漫画也含轻小说，映射为 manga 并允许用户
  手动改（个人数据优先，回填只在 NULL 时写、不覆盖用户值）。

---

## 二、数据关系图

```
                        items  (Work Core)
        ┌───────────────────┼───────────────────────┐
   内容形态 type        作品类型 work_type          世界轴列(alternative_title/
  (note/image/external_ref)  (anime/manga/...)       release_date/creator/series_name)
        │
   ┌────┼────────┬───────────┬────────────┬─────────┐
 chunks  reviews  memories     tags(M:N)   raw_metadata(JSON 兜底)

        │
   (P4 目标，本阶段不建表)
   Character ◄─(从 raw_metadata 提炼)─ Character-Work 关联
   Series ◄─(series_name 升级为 FK)─  Work
   Creator ◄─(creator 升级为 FK)─  Work
```

> 本阶段：`items` 是唯一作品容器，新增可查询列；关系表（character/series/creator）
> 在 P4 用"新表 + 幂等提炼回填"引入，届时 `items` 新增列要么删除要么降级为冗余展示
> （由 P4 ADR 决定）。

---

## 三、扩展策略

1. **新增作品类型**：改枚举 + 前端分组即可，不推倒架构（07 验收标准）；
2. **新增世界轴字段**：`ALTER TABLE items ADD COLUMN`（缺列才加）+ 幂等回填（只写 NULL），
   与既有 `ensure_schema` 模式一致（ADR 0010/0025 同款）；
3. **手动可改**：work_type/alternative_title/release_date/creator/series_name 全部允许
   UI 编辑（个人数据优先原则：外部数据不覆盖用户值，回填仅在 NULL 时发生）；
4. **多来源**：同一作品各来源各收藏一份的现状保留（ADR 0026），work_type/alternative_title
   不跨源合并；相关匹配继续走 `_title_key`（将来可叠加 alternative_title）。

---

## 四、数据库设计建议（迁移方案）

### 4.1 DDL（幂等）

```sql
ALTER TABLE items ADD COLUMN work_type VARCHAR(20);
ALTER TABLE items ADD COLUMN alternative_title VARCHAR(255);
ALTER TABLE items ADD COLUMN release_date VARCHAR(20);
ALTER TABLE items ADD COLUMN creator VARCHAR(255);
ALTER TABLE items ADD COLUMN series_name VARCHAR(255);
```

（`ensure_schema` 里 `insp.get_columns("items")` 缺列才加，SQLite 不支持 IF NOT EXISTS 加列）

### 4.2 回填（幂等，只填 NULL）

`app/ingest.py` 或新增 `app/work_model.py`：`backfill_work_columns(engine)`，启动时调用：

- 遍历 `items` 中 `source != 'local'` 且新列有 NULL 的行；
- 解析 `raw_metadata.detail.metadata`：
  - bangumi：`work_type`=type 映射、`alternative_title`=original_name、`release_date`=date；
  - 其它源：只填可确定的（目前无）；
- 用户已填的值（非 NULL）**不覆盖**；
- 幂等：重复运行只补缺口（与 `backfill_reviews` 同套路）。

### 4.3 数据安全

- 备份先行（复用 `backup.py`）；迁移在临时副本验证后再对真实库执行；
- 只加列不删列、只填 NULL，回滚 = 不执行/删除列，现有功能零破坏。

---

## 五、AI / RAG 支持方案

1. **结构化检索（Level 2）**：`work_type` / `release_date`(年份) 进入检索台结构化筛选
   （"我收藏的 galgame / 2025 年看的动画"），与 RAG 正交；
2. **世界轴不额外向量化**：作品简介已通过 `external_reference` chunk 参与检索
   （ADR 0025）；新列是结构化元数据，不重复 embedding；
3. **Personal RAG 预留（Phase G）**：Memory 进检索时，以所属作品的
   `work_type/series_name/alternative_title` 作为上下文过滤与回答锚点；
4. **AI 只增强不决定**：work_type 等由数据源/用户决定，AI 不做主来源；未来 AI 可做
   "建议补全"（如从简介推断类型）但需用户确认（07 第 11 节）。

---

## 六、影响范围与验收标准

**影响范围**：
- 后端：`models.py`(Item 加列) / `schemas.py`(ItemOut/ItemDetailOut 新字段) / `database.py`
  (ensure_schema 加列) / 新增回填函数(启动时调用) / `routes.py`（筛选参数 work_type）；
- 前端：详情页"外部世界"展示新字段（InfoTable 行）、资料库分组/命令面板按 work_type 筛选、
  条目编辑（work_type 手动改）；（UI 改动属于 P1 实现阶段，可另拆小步）
- 数据：63 条现有条目中外部条目按来源回填 work_type/alternative_title/release_date。

**验收标准**：
1. 迁移后旧数据无丢失、`integrity_check=ok`、回填幂等（重跑 0 变更）；
2. `GET /api/items?work_type=anime` 等筛选可用；
3. 详情页展示 原名/发行/类型；用户可手动改 work_type 且不被回填覆盖；
4. pytest/vitest 全绿（+迁移/回填/筛选/映射测试）。

---

## 七、待确认决策点

1. `galgame` 与 `visual_novel` 是否分开枚举（当前设计：分开）；
2. `creator` / `series_name` 是否本轮就落列（当前设计：落列，回填暂空、UI 可手填），
   还是等 P4 与实体表一起做；
3. work_type 手动编辑入口放在哪里（详情页"外部世界"区 vs 设置式管理）——建议详情页内联编辑。

> 确认后进入 P1 实现（含 ADR 0045：对 Item 的增量演进记录，不建新表，P4 前不建
> Character/Series/Creator 实体表）。
