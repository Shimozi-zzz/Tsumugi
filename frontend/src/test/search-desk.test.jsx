// P6 检索台（ADR 0050）：问答检索整合个人全文检索（作品/书评/记忆）
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import React from "react";
import DesktopView from "../components/DesktopView.jsx";

function ok(payload, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(payload) });
}

function mockFetch({ myWorks = [], myReviews = [], myMemories = [] } = {}) {
  global.fetch = vi.fn((url, opts = {}) => {
    const u = String(url);
    if (u.includes("/search/my")) return ok({ works: myWorks, reviews: myReviews, memories: myMemories });
    if (u.includes("/search/federated")) return ok({ results: [] });
    if (u.includes("/rag/query/stream")) return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "AI 未启用" }) });
    if (u.includes("/collections")) return ok([]);
    if (u.includes("/reviews")) return ok([]);
    if (u.includes("/memories")) return ok([]);
    if (u.includes("/items")) return ok({ total: 0, items: [] });
    if (u.includes("/tags")) return ok([]);
    if (u.includes("/connectors")) return ok([]);
    if (u.includes("/plugins")) return ok({ plugins: [], failures: [], notice_needed: false, plugin_dir: "./plugins" });
    return ok({});
  });
}

const PROPS = {
  items: [], total: 0, allTags: [], refresh: () => {},
  theme: "default", setTheme: () => {},
  custom: { accentHue: 0, density: "comfortable", radius: 16 }, updateCustom: () => {},
  textOverlays: [], updateTextOverlays: () => {},
};

beforeEach(() => { localStorage.clear(); document.documentElement.removeAttribute("data-theme"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("检索台（个人全文检索）", () => {
  it("输入查询提交后展示「我的检索」，含作品/书评/记忆并可点击", async () => {
    mockFetch({
      myWorks: [{ id: 1, title: "命运石之门", type: "external_ref", source: "bangumi", tags: [], chunks_count: 1 }],
      myReviews: [{ id: 10, item_id: 1, item_title: "命运石之门", title: "神作", content: "x", created_at: "2026-08-01T10:00:00" }],
      myMemories: [{ id: 9, item_id: 1, item_title: "命运石之门", source_type: "text", source_ref: null, summary: "关于孤独的感想", occurred_at: "2026-08-01T10:00:00" }],
    });
    render(<DesktopView {...PROPS} />);
    const input = screen.getByPlaceholderText("搜索知识库并提问…（Enter）");
    fireEvent.change(input, { target: { value: "孤独" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => expect(screen.getByText(/我的检索/)).toBeTruthy());
    expect(screen.getByText("作品")).toBeTruthy();
    expect(screen.getAllByText("命运石之门").length).toBeGreaterThan(0); // 作品/书评/记忆多处
    expect(screen.getByText("神作")).toBeTruthy();
    expect(screen.getByText("关于孤独的感想")).toBeTruthy();
    // 命中无结果时给出"没有匹配的我的记录"
  });

  it("个人检索无命中时显示空提示", async () => {
    mockFetch({});
    render(<DesktopView {...PROPS} />);
    const input = screen.getByPlaceholderText("搜索知识库并提问…（Enter）");
    fireEvent.change(input, { target: { value: "不存在的词" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => expect(screen.getByText(/没有匹配的我的记录/)).toBeTruthy());
  });
});
