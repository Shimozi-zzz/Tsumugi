// Memory 记忆时间轴（Phase B / ADR 0042）：时间轴渲染、正序、点击跳转只读书评、
// 空状态、ItemDetailPanel 双栏结构（外部世界/我的记录）四套主题兼容
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import React from "react";
import MemoryTimeline from "../components/MemoryTimeline.jsx";
import ItemDetailPanel from "../components/ItemDetailPanel.jsx";
import { applyTheme } from "../themes.js";

function ok(payload, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(payload) });
}

const MEMORIES = [
  { id: 1, item_id: 1, item_title: "命运石之门", source_type: "review", source_ref: 10, occurred_at: "2026-08-01T10:00:00", summary: "神作", created_at: "2026-08-01T10:00:00" },
  { id: 2, item_id: 1, item_title: "命运石之门", source_type: "review", source_ref: 11, occurred_at: "2026-08-15T20:30:00", summary: "二周目重看", created_at: "2026-08-15T20:30:00" },
];
const REVIEWS = [
  { id: 10, item_id: 1, item_title: "命运石之门", status: "看完", rating: 9, spoiler: false, font_size: null, title: "神作", content: "# 标题\n\n这是**神作**，强烈推荐。", created_at: "2026-08-01T10:00:00", public_rating: null },
  { id: 11, item_id: 1, item_title: "命运石之门", status: "在看", rating: 8, spoiler: false, font_size: null, title: "二周目重看", content: "还是好看。", created_at: "2026-08-15T20:30:00", public_rating: null },
];
const DETAIL = { id: 1, title: "命运石之门", source: "bangumi", description: "简介", rating: 8.9, my_rating: 9, tags: ["科幻"], reference_text: "", social: {}, raw_metadata: null, characters: [], image_url: null, file_path: null };

function mockFetch({ memories = MEMORIES, reviews = REVIEWS } = {}) {
  global.fetch = vi.fn((url) => {
    const u = String(url);
    const dm = u.match(/\/items\/(\d+)\/memories/);
    if (dm) return ok(memories);
    const dr = u.match(/\/items\/(\d+)\/reviews/);
    if (dr) return ok(reviews);
    const dd = u.match(/\/items\/(\d+)\/detail$/);
    if (dd) return ok(DETAIL);
    return ok({});
  });
}

beforeEach(() => { localStorage.clear(); document.documentElement.removeAttribute("data-theme"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("MemoryTimeline 时间轴", () => {
  it("正序（旧→新）渲染：日期 + 摘要，点击点用强调色", async () => {
    mockFetch();
    const { container } = render(<MemoryTimeline itemId={1} />);
    await waitFor(() => expect(screen.getByText("神作")).toBeTruthy());
    const items = [...container.querySelectorAll("button")];
    expect(items.length).toBe(2);
    // 正序：先旧后新（8-01 在 8-15 之前）
    expect(items[0].textContent).toContain("2026-08-01");
    expect(items[0].textContent).toContain("神作");
    expect(items[1].textContent).toContain("2026-08-15");
    // 时间轴点用 --accent（review 可点）
    expect(items[0].querySelector("span.rounded-full").style.backgroundColor).toBe("var(--accent)");
  });

  it("点击 review 记忆 → 只读弹层展示对应书评全文（markdown 已渲染）", async () => {
    mockFetch();
    render(<MemoryTimeline itemId={1} />);
    await waitFor(() => expect(screen.getByText("神作")).toBeTruthy());
    fireEvent.click(screen.getByText("神作"));
    await waitFor(() => {
      const heading = document.querySelector(".doc h1");
      expect(heading && heading.textContent).toBe("标题"); // renderMarkdown 渲染 <h1>
    });
    expect(screen.getByText(/评分 ★9/)).toBeTruthy();
    expect(screen.getByText(/状态 看完/)).toBeTruthy();
    // 关闭弹层
    fireEvent.click(screen.getByTitle("关闭"));
    expect(document.querySelector(".doc")).toBeNull();
  });

  it("空状态：没有记忆时给出引导，不显示空白", async () => {
    mockFetch({ memories: [] });
    render(<MemoryTimeline itemId={1} />);
    await waitFor(() => expect(screen.getByText(/还没有值得被记住的时刻/)).toBeTruthy());
  });

  it("非 review 来源的记忆不可点击（未来类型降级，不弹窗）", async () => {
    mockFetch({ memories: [{ id: 9, item_id: 1, item_title: "x", source_type: "collection", source_ref: null, occurred_at: "2026-08-01T10:00:00", summary: "这一天，我把它带回了图书馆", created_at: "2026-08-01T10:00:00" }] });
    render(<MemoryTimeline itemId={1} />);
    await waitFor(() => expect(screen.getByText(/带回了图书馆/)).toBeTruthy());
    fireEvent.click(screen.getByText(/带回了图书馆/));
    expect(document.querySelector(".doc")).toBeNull(); // 不打开书评弹层
  });

  it("itemId 变化时重新拉取", async () => {
    mockFetch({ memories: [{ id: 1, item_id: 1, item_title: "a", source_type: "review", source_ref: 10, occurred_at: "2026-08-01T10:00:00", summary: "第一条", created_at: "2026-08-01T10:00:00" }] });
    const { rerender } = render(<MemoryTimeline itemId={1} />);
    await waitFor(() => expect(screen.getByText("第一条")).toBeTruthy());
    mockFetch({ memories: [{ id: 2, item_id: 2, item_title: "b", source_type: "review", source_ref: 20, occurred_at: "2026-09-01T10:00:00", summary: "第二条", created_at: "2026-09-01T10:00:00" }] });
    rerender(<MemoryTimeline itemId={2} />);
    await waitFor(() => expect(screen.getByText("第二条")).toBeTruthy());
    expect(screen.queryByText("第一条")).toBeNull();
  });
});

describe("ItemDetailPanel 双栏结构（Phase B / ADR 0042）", () => {
  it("渲染「外部世界 · 世界如何描述它」与「我的记录 · 我如何理解它」两个区域", async () => {
    mockFetch();
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("命运石之门")).toBeTruthy());
    expect(screen.getByText("外部世界")).toBeTruthy();
    expect(screen.getByText("我的记录")).toBeTruthy();
    // 外部世界内容仍在（简介段落 + 标签）
    expect(screen.getAllByText(/简介/).length).toBeGreaterThan(0);
    expect(screen.getByText("科幻")).toBeTruthy();
    // 我的记录区包含时间轴（记忆条目渲染）
    await waitFor(() => expect(screen.getByText("神作")).toBeTruthy());
  });

  it("空库时详情页的我的记录区显示空状态引导", async () => {
    mockFetch({ memories: [] });
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("外部世界")).toBeTruthy());
    await waitFor(() => expect(screen.getByText(/还没有值得被记住的时刻/)).toBeTruthy());
  });
});

describe("四套主题兼容", () => {
  it("时间轴与双栏结构在 default/mint/sakura/dark 下均正常渲染", async () => {
    for (const theme of ["default", "mint", "sakura", "dark"]) {
      applyTheme(theme);
      mockFetch();
      const { container } = render(<ItemDetailPanel itemId={1} />);
      await waitFor(() => expect(screen.getByText("神作")).toBeTruthy());
      // 时间轴点使用 token 值（--accent 在不同主题派生不同，但结构一致）
      const dot = container.querySelector("button span.rounded-full");
      expect(dot.style.backgroundColor).toBe("var(--accent)");
      cleanup();
    }
  });
});
