# 0038 · 图书馆数据备份/导出/导入

日期：2026-08-08
状态：已接受

## 一、背景：兑现长期技术债

AGENTS.md"未来扩展点"里"本地库数据导出/备份"一直搁置。自托管场景下"数据能不能
安全导出/迁移"是刚需（本机 63 条目 / 57 书评 / 289 标签 / 活跃记录已有真实规模）。

## 二、导出格式选型：单个 JSON 文档（非 SQLite 文件）

选择 JSON 的理由（以"未来能被重新导入"为优先，而非格式先进性）：
- **可审计**：人是可读文本，导出前可检查是否含敏感信息（密钥为占位符）；
- **版本化**：文档带 `format=tsumugi-library` + `version=1`，未来 schema 变化可在导入
  时迁移，不依赖具体 SQLite 表结构；
- **可控范围**：只导出需要迁移的表（items/reviews/tags/sources/llm_providers），
  天然排除 chunks 与临时数据；SQLite 直接拷贝会把 chunks 指向丢失的向量、且受
  schema 演进影响。
- 文件命名带时间戳（`tsumugi-backup-2026-08-08-...json`），设置页一键下载。

## 三、向量库（Chroma）不导出的理由（确认）

1. **可再生成**：chunks + embedding 完全由原始内容（笔记/书评/外部 reference_text）
   推导，导入时经 ingest 重建，无需迁移；
2. **体积与耦合**：向量库大、与具体库版本/embedding 模型强耦合，导出/导入成本高
   于重建。

## 四、导入冲突处理策略（幂等合并）

- **条目**：外部按 `(source, external_id)`、本地笔记按 `content_hash`（内容指纹）
  去重——
  - 命中已有 → **刷新元数据**（title/content/image_url/raw_metadata/时间戳/标签），
    **不重建向量**（已有 chunks 保留），计入 items_updated；
  - 未命中 → 新建并**重建向量**（复用 ingest_text_document/ingest_external/
    ingest_image），计入 items_imported；
- **Review**：按 `(item_id, title, content)` 去重，命中跳过（reviews_skipped），
  未命中则 create_review 重建向量并保留原始 created_at；
- **标签**：按 name 幂等（get-or-create）；**数据源/LLM Provider**：按 name 幂等，
  config_ref / api_key_ref 只存**环境变量占位符**，不含明文密钥；
- 效果：导入到空实例 = 完整恢复；导入到已有实例 = 合并不产生重复；重复导入幂等。

## 五、触达方式与进度反馈

- 设置页新增「备份」tab：导出按钮（fetch → Blob → `<a download>` 带时间戳）；导入
  按钮（FileReader 读文件 → JSON → POST）；
- 导入走**后台线程**（`/backup/import` 返回 job_id → `/backup/import/status/{id}`
  轮询，复用 bangumi_import 的任务模式），前端显示进度条（当前条目/总数）与结果
  toast——大数据量下不阻塞前端。

## 六、测试与实测

- **pytest 386 passed**（+7 `test_backup.py`：导出完整性（items/reviews/tags/sources/
  llm_providers、raw_metadata 含下载资料、密钥为占位符）、导入到空实例完整恢复
  （含向量重建）、幂等合并（二次导入无重复/命中更新）、非法格式拒绝、导出/导入路由
  与任务状态）；build 通过。
- **实测（真实数据闭环）**：
  1. **真实导出**：本机库 → 646KB JSON（63 items / 57 reviews / 289 tags / 2 sources /
     2 llm_providers），0.1s 生成；抽查外部条目 raw_metadata 含角色、书评含评分，
     密钥为 `{DEEPSEEK_API_KEY}` 占位符；
  2. **导入到测试实例（全新临时 SQLite + 临时 Chroma）**：22s（含 bge 模型加载 +
     向量重建），恢复 63 items / 57 reviews / 289 tags，chunks 重建 89 条；
     抽查「命运石之门」reference_text 7081 字 + **22 条 external_reference chunk**
     完整保留，本地笔记的 note chunk 重建。
