// 相遇纪事 UI（Phase 3-2-C-1 / ADR 0076）：用户可观察行为，不测 CSS 实现细节。
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import React from "react";
import ItemDetailPanel from "../components/ItemDetailPanel.jsx";

const DETAIL = {
  id: 3, title: "命运石之门", source: "bangumi", description: "简介",
  rating: 8.9, tags: ["科幻"], characters: [],
  image_url: null, file_path: null, raw_metadata: null, social: {},
  collected_at: "2024-05-01T10:00:00", collection_status: "看完", favorite: true, my_rating: 9,
};
const MEMORIES = [
  { id: 1, item_id: 3, source_type: "text", source_ref: null, occurred_at: "2024-03-01T12:00:00", summary: "夜里重看", emotion: "怀念", created_at: "2024-03-02T00:00:00" },
  { id: 2, item_id: 3, source_type: "milestone", source_ref: null, occurred_at: "2024-08-20T21:00:00", summary: "这一天，我把《命运石之门》看完了", emotion: null, created_at: "2024-08-20T21:00:00" },
  { id: 3, item_id: 3, source_type: "collection", source_ref: 3, occurred_at: "2024-05-01T10:00:00", summary: "这一天，我把它带回了图书馆", emotion: null, created_at: "2024-05-01T10:00:00" },
  { id: 4, item_id: 3, source_type: "review", source_ref: 10, occurred_at: "2024-06-01T09:00:00", summary: "神作", emotion: null, created_at: "2024-06-01T09:00:00" },
];
const REVIEWS = [{ id: 10, item_id: 3, title: "神作", content: "x", rating: 9, status: "看完", spoiler: false, font_size: null, created_at: "2024-06-01T09:00:00", updated_at: "2024-07-01T00:00:00" }];

function mockFetch(detail = DETAIL, memories = MEMORIES, reviews = REVIEWS) {
  global.fetch = vi.fn((url) => {
    const u = String(url);
    if (u.includes("/detail")) return Promise.resolve({ ok: true, json: () => Promise.resolve(detail) });
    if (u.includes("/memories")) return Promise.resolve({ ok: true, json: () => Promise.resolve(memories) });
    if (u.includes("/reviews")) return Promise.resolve({ ok: true, json: () => Promise.resolve(reviews) });
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const chronicle = (container) => container.querySelector(".wd-encounter");

describe("相遇纪事（Phase 3-2-C-1）", () => {
  it("Collection / Review / text Memory / Milestone 事件全部显示，用各自事实时间", async () => {
    mockFetch();
    const { container } = render(<ItemDetailPanel itemId={3} />);
    await waitFor(() => expect(screen.getByText("命运石之门")).toBeTruthy());
    const enc = chronicle(container);
    expect(enc).toBeTruthy();
    const text = enc.textContent;
    // collection.added_at → 带回书架（2024.05.01）
    expect(text).toContain("2024.05.01");
    expect(text).toContain("带回书架");
    // review.created_at → 写下书评（2024.06.01），标题用书评标题
    expect(text).toContain("2024.06.01");
    expect(text).toContain("神作");
    // text memory.occurred_at → 留下一份记忆（2024.03.01）
    expect(text).toContain("2024.03.01");
    expect(text).toContain("夜里重看");
    // milestone.occurred_at → 用已有 summary
    expect(text).toContain("2024.08.20");
    expect(text).toContain("这一天，我把《命运石之门》看完了");
    // 冗余的 collection/review 类型记忆不重复出现（带回书架/神作 各一次）
    expect(text.split("带回书架").length - 1).toBe(1);
  });

  it("按 buildEncounterEvents 返回顺序（最早→最近）显示", async () => {
    mockFetch();
    const { container } = render(<ItemDetailPanel itemId={3} />);
    await waitFor(() => expect(screen.getByText("命运石之门")).toBeTruthy());
    const items = chronicle(container).querySelectorAll(".wd-encounter-item");
    const dates = Array.from(items).map((it) => it.querySelector(".wd-encounter-date").textContent);
    expect(dates[0]).toBe("2024.03.01"); // 最早
    expect(dates[dates.length - 1]).toBe("2024.08.20"); // 最近
  });

  it("同一天多个事件全部显示（不聚合不丢失）", async () => {
    mockFetch(
      { ...DETAIL, collected_at: "2025-01-01T08:00:00" },
      [{ id: 1, item_id: 3, source_type: "text", source_ref: null, occurred_at: "2025-01-01T09:00:00", summary: "白天看的", emotion: null, created_at: "2025-01-01T09:00:00" }],
      [{ id: 10, item_id: 3, title: null, content: "x", rating: null, status: null, spoiler: false, font_size: null, created_at: "2025-01-01T10:00:00", updated_at: "2025-01-01T10:00:00" }]
    );
    const { container } = render(<ItemDetailPanel itemId={3} />);
    await waitFor(() => expect(screen.getByText("命运石之门")).toBeTruthy());
    const items = chronicle(container).querySelectorAll(".wd-encounter-item");
    expect(items.length).toBe(3); // collection + review + text memory
    expect(chronicle(container).textContent).toContain("2025.01.01");
  });

  it("无任何可靠事件：整章隐藏", async () => {
    mockFetch({ ...DETAIL, collected_at: null }, [], []);
    const { container } = render(<ItemDetailPanel itemId={3} />);
    await waitFor(() => expect(screen.getByText("命运石之门")).toBeTruthy());
    expect(chronicle(container)).toBeNull();
    expect(screen.queryByText("相遇纪事")).toBeNull();
  });

  it("UI 不显示「第一次遇见」", async () => {
    mockFetch();
    render(<ItemDetailPanel itemId={3} />);
    await waitFor(() => expect(screen.getByText("命运石之门")).toBeTruthy());
    expect(screen.queryByText(/第一次遇见/)).toBeNull();
    expect(screen.queryByText(/尚未遇见/)).toBeNull();
  });
});
