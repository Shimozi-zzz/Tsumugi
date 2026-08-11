// 相遇纪事 View Model（Phase 3-2-C-0 / ADR 0076）
// 纯前端映射：把 Collection / Review / Memory 转成 EncounterEvent 列表。
//
// 原则：
// - 宁可少一个事件，也不把推断包装成事实；
// - 事件时间是「事实时间」：collection.added_at / review.created_at / memory.occurred_at，
//   不是系统写入时间（created_at）；
// - 不推导「第一次遇见」（最早用户痕迹 ≠ 第一次接触作品）；
// - 不聚合同日事件（每个独立事实保留一个事件；视觉聚合留到 UI 层）；
// - 无可靠事件时返回 []，由 UI 决定是否隐藏章节。
//
// 这是纯前端结构：不是数据库模型 / 后端 schema / 不需要 API / 不需要迁移。

export const ENCOUNTER_EVENT_TYPES = ["collection", "review", "memory", "milestone"];

const TYPE_RANK = { collection: 0, review: 1, memory: 2, milestone: 3 };

/**
 * 把作品的关系数据映射为相遇纪事事件。
 * @param {{ collection: {added_at?, status?, favorite?} | null,
 *           reviews: Array<{id, created_at?, title?, rating?}>,
 *           memories: Array<{id, source_type, occurred_at?, summary?, emotion?}> }} input
 * @returns {Array<{id, type, occurredAt, title, source, metadata}>} 时间升序
 */
export function buildEncounterEvents({ collection = null, reviews = [], memories = [] } = {}) {
  const events = [];

  // 带回书架（明确事实：collection.added_at 是收藏入库时间；缺失则不显示）
  if (collection && collection.added_at) {
    events.push({
      id: "collection",
      type: "collection",
      occurredAt: collection.added_at,
      title: "带回书架",
      source: "collection",
      metadata: { status: collection.status || null, favorite: !!collection.favorite },
    });
  }

  // 写下书评（明确事实：review.created_at 是创建书评时间；不使用 updated_at）
  for (const r of reviews || []) {
    if (!r.created_at) continue;
    events.push({
      id: `review-${r.id}`,
      type: "review",
      occurredAt: r.created_at,
      title: r.title || "写下书评",
      source: "review",
      metadata: { rating: r.rating ?? null },
    });
  }

  // 留下记忆 / 里程碑
  // - 仅 source_type=text 的直接记忆进纪事（occurred_at = 记忆实际发生时间）；
  // - review / collection 类型记忆与主事件重复，不重复进纪事；
  // - milestone 是明确事实（完成/重新打开发生过）；「完成 vs 重新打开」只能由 summary 文本
  //   表达（无结构化子类型），事件标题直接用 summary，不伪造结构化类型。
  for (const m of memories || []) {
    if (!m.occurred_at) continue;
    if (m.source_type === "text") {
      events.push({
        id: `memory-${m.id}`,
        type: "memory",
        occurredAt: m.occurred_at,
        title: m.summary || "留下一份记忆",
        source: "memory",
        metadata: { emotion: m.emotion || null },
      });
    } else if (m.source_type === "milestone") {
      events.push({
        id: `milestone-${m.id}`,
        type: "milestone",
        occurredAt: m.occurred_at,
        title: m.summary || "一个里程碑",
        source: "milestone",
        metadata: {},
      });
    }
  }

  // 排序：时间升序（最早 → 最近，表达"关系逐渐形成"，而非后台日志）；
  // 同时刻按类型/来源 id 稳定排序；不丢事件。
  events.sort((a, b) => {
    const ta = new Date(a.occurredAt).getTime() || 0;
    const tb = new Date(b.occurredAt).getTime() || 0;
    if (ta !== tb) return ta - tb;
    const ra = TYPE_RANK[a.type] ?? 9;
    const rb = TYPE_RANK[b.type] ?? 9;
    if (ra !== rb) return ra - rb;
    return String(a.id).localeCompare(String(b.id));
  });

  return events;
}
