// 相遇纪事数据规则（Phase 3-2-C-0 / ADR 0076）：验证事件映射规则，不验证 UI。
import { describe, it, expect } from "vitest";
import { buildEncounterEvents } from "../encounter.js";

const C = (added_at, status = null) => ({ added_at, status, favorite: 0 });
const R = (id, created_at, title = null) => ({ id, created_at, title, rating: 8 });
const T = (id, occurred_at, summary = null) => ({ id, source_type: "text", occurred_at, summary, emotion: null });
const M = (id, occurred_at, summary = null) => ({ id, source_type: "milestone", occurred_at, summary, emotion: null });
// 冗余类型记忆（不应重复进纪事）
const RM = (id, occurred_at) => ({ id, source_type: "review", occurred_at, summary: "书评记忆", emotion: null });
const CM = (id, occurred_at) => ({ id, source_type: "collection", occurred_at, summary: "收藏记忆", emotion: null });

describe("buildEncounterEvents 规则", () => {
  it("只有 Collection：1 条「带回书架」", () => {
    const ev = buildEncounterEvents({ collection: C("2024-05-01T10:00:00") });
    expect(ev).toHaveLength(1);
    expect(ev[0]).toMatchObject({ type: "collection", title: "带回书架", occurredAt: "2024-05-01T10:00:00" });
  });

  it("只有 Review：写下书评（用 created_at）", () => {
    const ev = buildEncounterEvents({ reviews: [R(1, "2024-06-01T09:00:00", "神作")] });
    expect(ev).toHaveLength(1);
    expect(ev[0]).toMatchObject({ type: "review", title: "神作", occurredAt: "2024-06-01T09:00:00" });
  });

  it("只有 text Memory：留下一份记忆（用 occurred_at 而非 created_at）", () => {
    const ev = buildEncounterEvents({ memories: [T(1, "2024-03-01T12:00:00", "夜里重看")] });
    expect(ev).toHaveLength(1);
    expect(ev[0]).toMatchObject({ type: "memory", title: "夜里重看", occurredAt: "2024-03-01T12:00:00" });
  });

  it("只有 Milestone：完成/重新打开以 summary 表达，不伪造结构化子类型", () => {
    const ev = buildEncounterEvents({ memories: [M(1, "2024-08-20T21:00:00", "这一天，我把《X》看完了")] });
    expect(ev).toHaveLength(1);
    expect(ev[0].type).toBe("milestone");
    expect(ev[0].title).toBe("这一天，我把《X》看完了");
  });

  it("Collection + Review + text Memory + Milestone 混合：按时间升序，事件全保留", () => {
    const ev = buildEncounterEvents({
      collection: C("2024-05-01T10:00:00"),
      reviews: [R(1, "2024-06-01T09:00:00")],
      memories: [T(1, "2024-03-01T12:00:00"), M(1, "2024-08-20T21:00:00")],
    });
    expect(ev).toHaveLength(4);
    const times = ev.map((e) => e.occurredAt);
    expect(times).toEqual([...times].sort()); // 升序
    expect(ev[0].type).toBe("memory"); // 2024-03 最早
    expect(ev[3].type).toBe("milestone"); // 2024-08 最晚
  });

  it("review/collection 类型记忆不重复进纪事（避免与主事件重复）", () => {
    const ev = buildEncounterEvents({
      collection: C("2024-05-01T10:00:00"),
      reviews: [R(1, "2024-06-01T09:00:00")],
      memories: [T(1, "2024-03-01T12:00:00"), RM(9, "2024-06-01T09:00:00"), CM(8, "2024-05-01T10:00:00")],
    });
    // 只有 text memory + collection + review，无 review/collection 类型记忆
    expect(ev).toHaveLength(3);
    expect(ev.some((e) => e.id === "memory-9" || e.id === "memory-8")).toBe(false);
  });

  it("collection.added_at 缺失：不显示「带回书架」", () => {
    const ev = buildEncounterEvents({ collection: C(null) });
    expect(ev).toHaveLength(0);
  });

  it("review.created_at 缺失：跳过该书评事件", () => {
    const ev = buildEncounterEvents({ reviews: [{ id: 1, created_at: null }] });
    expect(ev).toHaveLength(0);
  });

  it("同一天多个独立事件：全部保留，不聚合不丢失", () => {
    const ev = buildEncounterEvents({
      collection: C("2025-01-01T08:00:00"),
      reviews: [R(1, "2025-01-01T10:00:00")],
      memories: [T(1, "2025-01-01T09:00:00")],
    });
    expect(ev).toHaveLength(3);
    expect(new Set(ev.map((e) => e.type))).toEqual(new Set(["collection", "review", "memory"]));
  });

  it("没有任何可靠事件：返回空数组", () => {
    expect(buildEncounterEvents({})).toEqual([]);
    expect(buildEncounterEvents({ collection: null, reviews: [], memories: [] })).toEqual([]);
  });

  it("不会错误推导「第一次遇见」（无 first_seen/first_encounter 类型）", () => {
    const ev = buildEncounterEvents({
      collection: C("2024-05-01T10:00:00"),
      reviews: [R(1, "2024-06-01T09:00:00")],
      memories: [T(1, "2024-03-01T12:00:00")],
    });
    for (const e of ev) {
      expect(e.type).not.toBe("first_seen");
      expect(e.type).not.toBe("first_encounter");
    }
  });
});
