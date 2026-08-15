# 0099 · Phase 10-1-B-9：Ask Source Provenance Enhancement

日期：2026-08-12
状态：已接受
基准：B-5（memory metadata）、B-8（emotion/milestone）、B-9（source-aware cap）

## 一、决策

让 Ask「来源」展示个人记录的真实 provenance：仅 memory 来源显示 `occurred_at`（可读日期）、
`emotion`、`milestone`；review/note/external 不虚构 provenance。只透传 retrieval chunk 中
真实存在的 metadata，最小变更（API 新增 3 个可选字段，自动经 model_dump 透传）。

## 二、数据链路（最小透传）

- **retrieval → chunk**（app/retrieval.py）：hits 构建时从 Chroma metadata 读取
  occurred_at/emotion/milestone 写入 RetrievedChunk（仅存在时）。
- **API**（app/schemas.py）：RetrievedChunk 新增 `occurred_at: Optional[str]`、
  `emotion: Optional[str]`、`milestone: Optional[bool]`——`model_dump()` 自动透传到
  `/rag` sources payload（向后兼容；不存在时为 None）。
- **frontend**（DesktopView.jsx）：新增 `sourceProvenance(s)`——仅 `source_type=="memory"`
  且字段存在时拼「· YYYY-MM-DD · 情绪 · 里程碑」；`ask-source-provenance`（mono 10px ink-2）
  渲染在来源标签旁。review/note/external 不显示。
- 不修改：retrieve_chunks 签名、`_compute_retrieval_score`、`_source_weight`、intent、
  temporal/emotion/milestone rules、candidate pool、top_k、cap、embedding、Chroma schema、
  Memory/Review schema。

## 三、验证

- 后端 pytest **483 passed**（482 + 1：memory 的 occurred_at/emotion/milestone 进入 chunk 且
  model_dump 透传；无信号 chunk 字段为 None）；cov 86.08% ≥70%。
- 前端 vitest **296 passed**；build 通过。
- 真实浏览器（真实库）：先经 API 创建一条 emotion="怀念" 的直接记忆（B-5 写入带
  occurred_at/emotion metadata），Ask 查询「哪些作品让我印象深刻」→ 来源首行
  「我的记忆 · 2026-08-15 · 怀念」（0.80，emotion boost 助其置顶）；书评/百科 无 provenance；
  hOverflow=false。截图 `prov101b9_1440.png`。
