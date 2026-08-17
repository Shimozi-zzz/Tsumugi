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

describe("外部检索多来源卡片（Phase 11-C）", () => {
  function mockFetchFed(fedResults) {
    global.fetch = vi.fn((url, opts = {}) => {
      const u = String(url);
      if (u.includes("/search/my")) return ok({ works: [], reviews: [], memories: [] });
      if (u.includes("/search/federated")) return ok({ results: fedResults, local_results: [], errors: {} });
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

  it("卡片显示原名/年份/标签/评分与多来源徽标；空字段隐藏", async () => {
    mockFetchFed([
      { source: "bangumi", title: "命运石之门", subtitle: "STEINS;GATE", external_id: "123",
        year: 2011, type: "anime", rating: 8.9, tags: ["科幻", "悬疑"],
        sources: [{ source: "bangumi", external_id: "123" }, { source: "anilist", external_id: "9253" }] },
      { source: "anilist", title: "Steins;Gate 0", external_id: "999", year: 2018,
        sources: [{ source: "anilist", external_id: "999" }] },
    ]);
    render(<DesktopView {...PROPS} />);
    const input = screen.getByPlaceholderText("搜索知识库并提问…（Enter）");
    fireEvent.change(input, { target: { value: "Steins;Gate" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => expect(screen.getByText("命运石之门")).toBeTruthy());
    expect(screen.getByText("STEINS;GATE")).toBeTruthy();      // 原名
    expect(screen.getByText(/科幻/)).toBeTruthy();               // 标签
    expect(screen.getByText("★ 8.9")).toBeTruthy();             // 评分
    expect(screen.getAllByText("2018").length).toBeGreaterThan(0); // 第二卡片年份(含年份筛选chip)
    // 多来源徽标：Bangumi · AniList
    expect(screen.getAllByText("Bangumi").length).toBeGreaterThan(0);
    expect(screen.getAllByText("AniList").length).toBeGreaterThan(0);
    // 空字段隐藏：Steins;Gate 0 无 type → 仅第一张卡渲染 "anime"
    expect(screen.getAllByText("anime").length).toBe(1);
  });

  it("无来源聚合时显示单源徽标（旧客户端兼容）", async () => {
    mockFetchFed([
      { source: "vndb", title: "STEINS;GATE", external_id: "v2002",
        sources: [{ source: "vndb", external_id: "v2002" }] },
    ]);
    render(<DesktopView {...PROPS} />);
    const input = screen.getByPlaceholderText("搜索知识库并提问…（Enter）");
    fireEvent.change(input, { target: { value: "Steins" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => expect(screen.getByText("STEINS;GATE")).toBeTruthy());
    expect(screen.getAllByText("VNDB").length).toBeGreaterThan(0);
  });

  it("来源筛选：点 AniList 只显示 AniList 结果（前端过滤）", async () => {
    mockFetchFed([
      { source: "bangumi", title: "作品A", external_id: "1",
        sources: [{ source: "bangumi", external_id: "1" }] },
      { source: "anilist", title: "作品B", external_id: "2",
        sources: [{ source: "anilist", external_id: "2" }] },
    ]);
    render(<DesktopView {...PROPS} />);
    const input = screen.getByPlaceholderText("搜索知识库并提问…（Enter）");
    fireEvent.change(input, { target: { value: "作品" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => expect(screen.getByText("作品A")).toBeTruthy());
    expect(screen.getByText("作品B")).toBeTruthy();
    // 点击筛选按钮（settings-tab，非卡片徽标）
    const aniBtn = screen.getAllByRole("button").find((b) => b.textContent === "AniList" && b.className.includes("settings-tab"));
    fireEvent.click(aniBtn);
    await waitFor(() => expect(screen.queryByText("作品A")).toBeNull());
    expect(screen.getByText("作品B")).toBeTruthy();
  });

  it("类型/年份筛选（前端过滤，Phase 12-D）", async () => {
    mockFetchFed([
      { source: "anilist", title: "AnimeX", external_id: "1", type: "anime", year: 2020,
        sources: [{ source: "anilist", external_id: "1" }] },
      { source: "anilist", title: "MangaX", external_id: "2", type: "manga", year: 2021,
        sources: [{ source: "anilist", external_id: "2" }] },
    ]);
    render(<DesktopView {...PROPS} />);
    const input = screen.getByPlaceholderText("搜索知识库并提问…（Enter）");
    fireEvent.change(input, { target: { value: "X" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => expect(screen.getByText("AnimeX")).toBeTruthy());
    expect(screen.getByText("MangaX")).toBeTruthy();
    // 类型：Anime → 只剩 AnimeX
    const animeBtn = screen.getAllByRole("button").find((b) => b.textContent === "Anime");
    fireEvent.click(animeBtn);
    await waitFor(() => expect(screen.queryByText("MangaX")).toBeNull());
    expect(screen.getByText("AnimeX")).toBeTruthy();
    // 清空类型 → 全部
    fireEvent.click(screen.getAllByRole("button").find((b) => b.textContent === "类型：全部"));
    await waitFor(() => expect(screen.getByText("MangaX")).toBeTruthy());
    // 年份：2021 → 只剩 MangaX
    fireEvent.click(screen.getAllByRole("button").find((b) => b.textContent === "2021"));
    await waitFor(() => expect(screen.queryByText("AnimeX")).toBeNull());
    expect(screen.getByText("MangaX")).toBeTruthy();
  });
});
