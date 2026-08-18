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


describe("搜索本地状态与空状态（Phase 13-B）", () => {
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
  const PROPS2 = { items: [], total: 0, allTags: [], refresh: () => {},
    theme: "default", setTheme: () => {},
    custom: { accentHue: 0, density: "comfortable", radius: 16 }, updateCustom: () => {},
    textOverlays: [], updateTextOverlays: () => {} };

  it("已收藏结果显示「打开」而非「收藏」", async () => {
    mockFetchFed([
      { source: "anilist", title: "已收藏作", external_id: "1", is_local: true, local_item_id: 42, sources: [{ source: "anilist", external_id: "1" }] },
    ]);
    render(<DesktopView {...PROPS2} />);
    const input = screen.getByPlaceholderText("搜索知识库并提问…（Enter）");
    fireEvent.change(input, { target: { value: "X" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => expect(screen.getByText("已收藏作")).toBeTruthy());
    expect(screen.getByText("打开")).toBeTruthy();
  });

  it("无结果时显示探索块", async () => {
    mockFetchFed([]);
    render(<DesktopView {...PROPS2} />);
    const input = screen.getByPlaceholderText("搜索知识库并提问…（Enter）");
    fireEvent.change(input, { target: { value: "不存在的词" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => expect(screen.getByText("没有找到匹配作品")).toBeTruthy());
    expect(screen.getByText("浏览我的收藏")).toBeTruthy();
  });
});


describe("搜索空状态探索（Phase 13-C）", () => {
  function mockFetchExplore(items) {
    global.fetch = vi.fn((url) => {
      const u = String(url);
      if (u.includes("/search/my")) return ok({ works: [], reviews: [], memories: [] });
      if (u.includes("/search/federated")) return ok({ results: [], local_results: [], errors: {} });
      if (u.includes("/rag/query/stream")) return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "AI 未启用" }) });
      if (u.includes("/collections")) return ok([]);
      if (u.includes("/reviews")) return ok([]);
      if (u.includes("/memories")) return ok([]);
      if (u.includes("/items")) return ok({ total: items.length, items });
      if (u.includes("/tags")) return ok([]);
      if (u.includes("/connectors")) return ok([]);
      if (u.includes("/plugins")) return ok({ plugins: [], failures: [], notice_needed: false, plugin_dir: "./plugins" });
      return ok({});
    });
  }
  const PROPS3 = { items: [], total: 0, allTags: [], refresh: () => {},
    theme: "default", setTheme: () => {},
    custom: { accentHue: 0, density: "comfortable", radius: 16 }, updateCustom: () => {},
    textOverlays: [], updateTextOverlays: () => {} };

  it("空状态显示题材/制作/类型入口，点击跳转图书馆并应用筛选", async () => {
    mockFetchExplore([
      { id: 1, title: "科幻作", type: "external_ref", source: "bangumi", tags: [],
        genres: ["科幻"], studios: ["White Fox"], work_type: "anime", collected_at: null },
      { id: 2, title: "恋爱作", type: "external_ref", source: "bangumi", tags: [],
        genres: ["恋爱"], studios: [], work_type: "manga", collected_at: null },
    ]);
    render(<DesktopView {...PROPS3} />);
    const input = screen.getByPlaceholderText("搜索知识库并提问…（Enter）");
    fireEvent.change(input, { target: { value: "不存在的词" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => expect(screen.getByText("没有找到匹配作品")).toBeTruthy());
    await waitFor(() => expect(screen.getByText("题材 · 科幻")).toBeTruthy());
    expect(screen.getByText("制作 · White Fox")).toBeTruthy();
    expect(screen.getByText("类型 · 动画")).toBeTruthy();
    fireEvent.click(screen.getByText("题材 · 科幻"));
    await waitFor(() => expect(screen.getByText("共 2 册")).toBeTruthy());
    // 已进入图书馆且筛选生效：只剩科幻作
    await waitFor(() => expect(screen.getByText("科幻作")).toBeTruthy());
    expect(screen.queryByText("恋爱作")).toBeNull();
  });
});


describe("本地搜索结果导航（Phase 14-B）", () => {
  function mockLocal() {
    const calls = { localDetail: 0, externalDetail: 0 };
    global.fetch = vi.fn((url) => {
      const u = String(url);
      if (u.includes("/search/my")) return ok({ works: [], reviews: [], memories: [] });
      if (u.includes("/search/federated")) return ok({ results: [
        { source: "bangumi", title: "本地作", external_id: "123", is_local: true, local_item_id: 123,
          sources: [{ source: "bangumi", external_id: "123" }] }], local_results: [], errors: {} });
      if (u.includes("/rag/query/stream")) return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "AI 未启用" }) });
      if (u.includes("/external/detail")) { calls.externalDetail += 1; return ok({}); }
      if (u.match(/\/items\/123\/detail$/)) { calls.localDetail += 1; return ok({ id: 123, title: "本地作", source: "bangumi", description: "本地详情", tags: [], characters: [], relations: [], sources: [], image_url: null }); }
      if (u.includes("/items")) return ok({ total: 0, items: [] });
      if (u.includes("/tags")) return ok([]);
      if (u.includes("/connectors")) return ok([]);
      if (u.includes("/collections")) return ok([]);
      if (u.includes("/reviews")) return ok([]);
      if (u.includes("/memories")) return ok([]);
      if (u.includes("/plugins")) return ok({ plugins: [], failures: [], notice_needed: false, plugin_dir: "./plugins" });
      return ok({});
    });
    return calls;
  }
  const PROPS14 = { items: [], total: 0, allTags: [], refresh: () => {},
    theme: "default", setTheme: () => {},
    custom: { accentHue: 0, density: "comfortable", radius: 16 }, updateCustom: () => {},
    textOverlays: [], updateTextOverlays: () => {} };

  async function doSearch() {
    const input = screen.getByPlaceholderText("搜索知识库并提问…（Enter）");
    fireEvent.change(input, { target: { value: "X" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => expect(screen.getByText("本地作")).toBeTruthy());
  }

  it("已收藏结果点「详情」→ 直接进本地 ItemDetailPanel，不请求 /external/detail", async () => {
    const calls = mockLocal();
    render(<DesktopView {...PROPS14} />);
    await doSearch();
    fireEvent.click(screen.getByText("详情"));
    await waitFor(() => expect(calls.localDetail).toBeGreaterThan(0));
    expect(screen.getByText("作品档案")).toBeTruthy(); // 打开本地 ItemDetailPanel
    expect(calls.externalDetail).toBe(0);              // 未触发 Provider
  });

  it("已收藏结果点标题/封面同样进本地详情（共用 handler），不请求 /external/detail", async () => {
    const calls = mockLocal();
    render(<DesktopView {...PROPS14} />);
    await doSearch();
    // 标题点击
    fireEvent.click(screen.getByText("本地作"));
    await waitFor(() => expect(calls.localDetail).toBeGreaterThan(0));
    expect(calls.externalDetail).toBe(0);
    // 关闭详情后点封面
    fireEvent.click(screen.getByTitle("关闭"));
    await waitFor(() => expect(calls.localDetail).toBe(1));
    fireEvent.click(screen.getByLabelText("查看详情"));
    await waitFor(() => expect(calls.localDetail).toBe(2));
    expect(calls.externalDetail).toBe(0);
  });
});


describe("收藏后本地状态同步（Phase 14-B）", () => {
  const PROPS15 = { items: [], total: 0, allTags: [], refresh: () => {},
    theme: "default", setTheme: () => {},
    custom: { accentHue: 0, density: "comfortable", radius: 16 }, updateCustom: () => {},
    textOverlays: [], updateTextOverlays: () => {} };

  it("收藏成功 → 卡片立即「打开」→ 点击进本地详情，不请求 Provider", async () => {
    let externalCalls = 0;
    global.fetch = vi.fn((url, opts = {}) => {
      const u = String(url);
      const m = opts.method || "GET";
      if (u.includes("/search/my")) return ok({ works: [], reviews: [], memories: [] });
      if (u.includes("/search/federated")) return ok({ results: [
        { source: "bangumi", title: "未收藏作", external_id: "456", is_local: false, local_item_id: null,
          sources: [{ source: "bangumi", external_id: "456" }] }], local_results: [], errors: {} });
      if (u.includes("/items/save-external")) return ok({ item_id: 99, title: "未收藏作", type: "external_ref", chunks_count: 1, tags: [] });
      if (u.includes("/external/detail")) { externalCalls += 1; return ok({}); }
      if (u.match(/\/items\/99\/detail$/)) return ok({ id: 99, title: "未收藏作", source: "bangumi", description: "", tags: [], characters: [], relations: [], sources: [], image_url: null });
      if (u.includes("/rag/query/stream")) return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "AI 未启用" }) });
      if (u.includes("/items") && m === "GET") return ok({ total: 0, items: [] });
      if (u.includes("/tags")) return ok([]);
      if (u.includes("/connectors")) return ok([]);
      if (u.includes("/collections")) return ok([]);
      if (u.includes("/reviews")) return ok([]);
      if (u.includes("/memories")) return ok([]);
      if (u.includes("/plugins")) return ok({ plugins: [], failures: [], notice_needed: false, plugin_dir: "./plugins" });
      return ok({});
    });
    render(<DesktopView {...PROPS15} />);
    const input = screen.getByPlaceholderText("搜索知识库并提问…（Enter）");
    fireEvent.change(input, { target: { value: "X" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => expect(screen.getByText("未收藏作")).toBeTruthy());
    expect(screen.getByText("收藏")).toBeTruthy();
    // 收藏成功 → 卡片立即变「打开」
    fireEvent.click(screen.getByText("收藏"));
    await waitFor(() => expect(screen.getByText("打开")).toBeTruthy());
    expect(screen.queryByText("收藏")).toBeNull();
    // 点「打开」→ 本地 ItemDetailPanel，不请求 Provider
    fireEvent.click(screen.getByText("打开"));
    await waitFor(() => expect(screen.getByText("作品档案")).toBeTruthy());
    expect(externalCalls).toBe(0);
  });
});


describe("本地状态边界（Phase 14-C）", () => {
  const PROPS16 = { items: [], total: 0, allTags: [], refresh: () => {},
    theme: "default", setTheme: () => {},
    custom: { accentHue: 0, density: "comfortable", radius: 16 }, updateCustom: () => {},
    textOverlays: [], updateTextOverlays: () => {} };

  function mockResult({ externalId, localItemId, source = "bangumi" }) {
    const state = { fetched: [], externalDetail: 0, saveExternal: 0 };
    global.fetch = vi.fn((url, opts = {}) => {
      const u = String(url);
      const m = opts.method || "GET";
      state.fetched.push(u);
      if (u.includes("/search/my")) return ok({ works: [], reviews: [], memories: [] });
      if (u.includes("/search/federated")) return ok({ results: [
        { source, title: "边界作", external_id: externalId, is_local: true, local_item_id: localItemId,
          sources: [{ source, external_id: externalId }] }], local_results: [], errors: {} });
      if (u.includes("/items/save-external")) { state.saveExternal += 1; return ok({ item_id: 77, title: "边界作", type: "external_ref", chunks_count: 1, tags: [] }); }
      if (u.includes("/external/detail")) { state.externalDetail += 1; return ok({ source, title: "外部详情", external_id: String(externalId) }); }
      if (u.includes("/rag/query/stream")) return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "AI 未启用" }) });
      if (u.includes("/items") && m === "GET") return ok({ total: 0, items: [] });
      if (u.includes("/tags")) return ok([]);
      if (u.includes("/connectors")) return ok([]);
      if (u.includes("/collections")) return ok([]);
      if (u.includes("/reviews")) return ok([]);
      if (u.includes("/memories")) return ok([]);
      if (u.includes("/plugins")) return ok({ plugins: [], failures: [], notice_needed: false, plugin_dir: "./plugins" });
      return ok({});
    });
    return state;
  }

  async function doSearch() {
    const input = screen.getByPlaceholderText("搜索知识库并提问…（Enter）");
    fireEvent.change(input, { target: { value: "X" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => expect(screen.getByText("边界作")).toBeTruthy());
  }

  it("is_local=true + local_item_id=null：不调用 openItemDetail(null)，走安全 fallback", async () => {
    const state = mockResult({ externalId: "123", localItemId: null });
    render(<DesktopView {...PROPS16} />);
    await doSearch();
    fireEvent.click(screen.getByText("详情"));
    await waitFor(() => expect(state.externalDetail).toBeGreaterThan(0)); // fallback 到外部详情
    expect(state.fetched.some((u) => u.includes("/items/null/detail"))).toBe(false);
    expect(state.fetched.some((u) => /\/items\/\/detail/.test(u))).toBe(false);
  });

  it("is_local=true + local_item_id=空串：不调用 openItemDetail(\"\")，走安全 fallback", async () => {
    const state = mockResult({ externalId: "123", localItemId: "" });
    render(<DesktopView {...PROPS16} />);
    await doSearch();
    fireEvent.click(screen.getByText("详情"));
    await waitFor(() => expect(state.externalDetail).toBeGreaterThan(0));
    expect(state.fetched.some((u) => u.includes("/items//detail"))).toBe(false);
    expect(state.fetched.some((u) => /\/items\/\/detail/.test(u))).toBe(false);
  });

  it("external_id 为数字：收藏成功后 String() 归一匹配并翻转为本地", async () => {
    const state = mockResult({ externalId: 123, localItemId: null });
    render(<DesktopView {...PROPS16} />);
    await doSearch();
    // is_local=true 但无有效 local_item_id → 按钮显示「收藏」（安全恢复路径）
    expect(screen.getByText("收藏")).toBeTruthy();
    fireEvent.click(screen.getByText("收藏"));
    await waitFor(() => expect(screen.getByText("打开")).toBeTruthy());
    expect(state.saveExternal).toBe(1);
  });
});


describe("收藏同步边界（Phase 14-C）", () => {
  const PROPS17 = { items: [], total: 0, allTags: [], refresh: () => {},
    theme: "default", setTheme: () => {},
    custom: { accentHue: 0, density: "comfortable", radius: 16 }, updateCustom: () => {},
    textOverlays: [], updateTextOverlays: () => {} };

  it("不同 source 相同 external_id：只更新 source 匹配的结果", async () => {
    global.fetch = vi.fn((url, opts = {}) => {
      const u = String(url);
      const m = opts.method || "GET";
      if (u.includes("/search/my")) return ok({ works: [], reviews: [], memories: [] });
      if (u.includes("/search/federated")) return ok({ results: [
        { source: "bangumi", title: "作品甲", external_id: "123", is_local: false, local_item_id: null, sources: [{ source: "bangumi", external_id: "123" }] },
        { source: "anilist", title: "作品乙", external_id: "123", is_local: false, local_item_id: null, sources: [{ source: "anilist", external_id: "123" }] },
      ], local_results: [], errors: {} });
      if (u.includes("/items/save-external")) return ok({ item_id: 77, title: "作品甲", type: "external_ref", chunks_count: 1, tags: [] });
      if (u.includes("/rag/query/stream")) return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "AI 未启用" }) });
      if (u.includes("/items") && m === "GET") return ok({ total: 0, items: [] });
      if (u.includes("/tags")) return ok([]);
      if (u.includes("/connectors")) return ok([]);
      if (u.includes("/collections")) return ok([]);
      if (u.includes("/reviews")) return ok([]);
      if (u.includes("/memories")) return ok([]);
      if (u.includes("/plugins")) return ok({ plugins: [], failures: [], notice_needed: false, plugin_dir: "./plugins" });
      return ok({});
    });
    render(<DesktopView {...PROPS17} />);
    const input = screen.getByPlaceholderText("搜索知识库并提问…（Enter）");
    fireEvent.change(input, { target: { value: "X" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => expect(screen.getByText("作品甲")).toBeTruthy());
    // 点第一个「收藏」（bangumi 作品甲）
    fireEvent.click(screen.getAllByText("收藏")[0]);
    await waitFor(() => expect(screen.getByText("打开")).toBeTruthy());
    // 只剩一个「收藏」（anilist 作品乙，未被误改）
    expect(screen.getAllByText("收藏").length).toBe(1);
    expect(screen.getByText("作品乙")).toBeTruthy();
  });

  it("收藏失败：fedResults 不得被标记为 local", async () => {
    global.fetch = vi.fn((url, opts = {}) => {
      const u = String(url);
      const m = opts.method || "GET";
      if (u.includes("/search/my")) return ok({ works: [], reviews: [], memories: [] });
      if (u.includes("/search/federated")) return ok({ results: [
        { source: "bangumi", title: "失败作", external_id: "123", is_local: false, local_item_id: null,
          sources: [{ source: "bangumi", external_id: "123" }] }], local_results: [], errors: {} });
      if (u.includes("/items/save-external")) return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "保存失败" }) });
      if (u.includes("/rag/query/stream")) return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "AI 未启用" }) });
      if (u.includes("/items") && m === "GET") return ok({ total: 0, items: [] });
      if (u.includes("/tags")) return ok([]);
      if (u.includes("/connectors")) return ok([]);
      if (u.includes("/collections")) return ok([]);
      if (u.includes("/reviews")) return ok([]);
      if (u.includes("/memories")) return ok([]);
      if (u.includes("/plugins")) return ok({ plugins: [], failures: [], notice_needed: false, plugin_dir: "./plugins" });
      return ok({});
    });
    render(<DesktopView {...PROPS17} />);
    const input = screen.getByPlaceholderText("搜索知识库并提问…（Enter）");
    fireEvent.change(input, { target: { value: "X" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => expect(screen.getByText("失败作")).toBeTruthy());
    expect(screen.getByText("收藏")).toBeTruthy();
    fireEvent.click(screen.getByText("收藏"));
    await waitFor(() => expect(screen.getByText("保存失败")).toBeTruthy()); // toast 错误
    expect(screen.getByText("收藏")).toBeTruthy();  // 卡片仍为「收藏」，未被误标 local
    expect(screen.queryByText("打开")).toBeNull();
  });
});
