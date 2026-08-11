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
    // 档案编号：条目带 §01 / §02（正序序号）
    const nos = [...container.querySelectorAll('[data-testid="archive-no"]')].map((e) => e.textContent);
    expect(nos[0]).toContain("§");
    expect(nos[0]).toContain("01");
    expect(nos[1]).toContain("02");
    // 时间轴点用 --accent（review 可点；点在按钮外层的包裹 div 里，即按钮前一个兄弟）
    const dot = items[0].previousElementSibling;
    expect(dot.className).toContain("rounded-full");
    expect(dot.style.backgroundColor).toBe("var(--accent)");
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
    expect(screen.getByText("＋ 收藏")).toBeTruthy(); // Phase D：收藏时刻类型标记
    fireEvent.click(screen.getByText(/带回了图书馆/));
    expect(document.querySelector(".doc")).toBeNull(); // 不打开书评弹层
  });

  it("Phase D：完成时刻（milestone）显示「✓ 完成」标记，可删除", async () => {
    mockFetch({ memories: [
      { id: 7, item_id: 1, item_title: "魔法少女小圆", source_type: "milestone", source_ref: null, occurred_at: "2026-08-20T21:00:00", summary: "这一天，我把《魔法少女小圆》看完了", created_at: "2026-08-20T21:00:00" },
    ] });
    render(<MemoryTimeline itemId={1} />);
    await waitFor(() => expect(screen.getByText(/看完了/)).toBeTruthy());
    expect(screen.getByText("✓ 完成")).toBeTruthy();
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

  it("P3：text 记忆显示「记录」徽标 + 情绪，点击弹出直接内容，可删除", async () => {
    mockFetch({ memories: [
      { id: 5, item_id: 1, item_title: "x", source_type: "text", source_ref: null, occurred_at: "2026-08-01T10:00:00", summary: "今天重温，还是很感动", emotion: "感动", media: [{ id: 1, url: "/static/uploads/a.png", media_type: "image" }], created_at: "2026-08-01T10:00:00" },
    ] });
    const { container } = render(<MemoryTimeline itemId={1} />);
    await waitFor(() => expect(screen.getByText("今天重温，还是很感动")).toBeTruthy());
    expect(screen.getByText("记录")).toBeTruthy();   // 类型徽标
    expect(screen.getAllByText(/感动/).length).toBeGreaterThan(0); // 情绪
    expect(container.querySelector("img")).toBeTruthy(); // 媒体缩略图
    fireEvent.click(screen.getByText("今天重温，还是很感动"));
    await waitFor(() => expect(document.querySelector(".doc")).toBeTruthy());
    expect(document.querySelector(".doc").textContent).toContain("今天重温");
    fireEvent.click(screen.getByTitle("关闭"));
    // 删除
    fireEvent.click(screen.getByTitle("删除这条记忆"));
    await waitFor(() => expect(screen.queryByText("今天重温，还是很感动")).toBeNull());
  });
});

describe("ItemDetailPanel 双栏结构（Phase B / ADR 0042）", () => {
  it("渲染「这个世界」与「我与它」两个区域", async () => {
    mockFetch();
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("命运石之门")).toBeTruthy());
    expect(screen.getByText("这个世界")).toBeTruthy();
    expect(screen.getByText("我与它")).toBeTruthy();
    // 详情标题带编目号（ADR 0056）
    expect(screen.getByText("NO. 0001")).toBeTruthy();
    // 这个世界内容仍在（简介段落 + 标签）
    expect(screen.getAllByText(/简介/).length).toBeGreaterThan(0);
    expect(screen.getByText("科幻")).toBeTruthy();
    // 我与它包含 书评入口 + 我的记忆区包含时间轴（记忆条目渲染；「神作」同时出现在
    // 相遇纪事的书评事件标题与时间轴，故用 getAllByText）
    expect(screen.getByTitle("打开书评工作室")).toBeTruthy();
    await waitFor(() => expect(screen.getAllByText("神作").length).toBeGreaterThan(0));
  });

  it("空库时详情页的我的记录区显示空状态引导", async () => {
    mockFetch({ memories: [] });
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("这个世界")).toBeTruthy());
    await waitFor(() => expect(screen.getByText(/还没有值得被记住的时刻/)).toBeTruthy());
  });
});

describe("Phase 3-1 统一 Work Detail（外部未收藏模式）", () => {
  it("外部详情：收藏入库 + 这个世界，无我与它/composer/时间轴", () => {
    const ext = { source: "bangumi", title: "外部作品", external_id: "x1", description: "外部简介", rating: 8, tags: ["热血"], characters: [] };
    render(<ItemDetailPanel externalDetail={ext} onSaveDetail={() => {}} />);
    expect(screen.getByText("外部作品")).toBeTruthy();
    expect(screen.getByText("收藏入库")).toBeTruthy();
    expect(screen.getByText("这个世界")).toBeTruthy();
    expect(screen.queryByText("我与它")).toBeNull();
    expect(screen.queryByText("✓ 完成了")).toBeNull();
    expect(screen.queryByText("书评")).toBeNull();
  });

  it("已收藏模式：传安利卡/刷新回调时渲染对应按钮 + 我与它", async () => {
    mockFetch();
    render(<ItemDetailPanel itemId={1} onShareDetail={() => {}} onRefreshDetail={() => {}} />);
    await waitFor(() => expect(screen.getByText("命运石之门")).toBeTruthy());
    expect(screen.getByText("生成安利卡")).toBeTruthy();
    expect(screen.getByText("刷新资料")).toBeTruthy();
    expect(screen.getByText("我与它")).toBeTruthy();
  });
});

describe("我的记忆章节（Phase 3-2-D）", () => {
  it("章节存在：我的记忆 · MY MEMORY；composer 与 MemoryTimeline 归位", async () => {
    mockFetch();
    const { container } = render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("命运石之门")).toBeTruthy());
    expect(screen.getByText("我的记忆")).toBeTruthy();
    expect(screen.getByText("MY MEMORY")).toBeTruthy();
    // composer 归位（输入区 + 主动作按钮「记录这一刻」）
    expect(screen.getByPlaceholderText(/写一句此刻的感想/)).toBeTruthy();
    expect(screen.getByText("记录这一刻")).toBeTruthy();
    // MemoryTimeline 归位（记忆条目渲染）
    await waitFor(() => expect(screen.getAllByText("神作").length).toBeGreaterThan(0));
    // 没有重复 composer / 没有重复 MemoryTimeline
    expect(screen.getAllByText("记录这一刻").length).toBe(1);
    expect(container.querySelectorAll(".relative.pl-5").length).toBe(1);
  });

  it("章节顺序：这个世界 → 我与它 → 相遇纪事 → 我的记忆", async () => {
    mockFetch();
    const { container } = render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("命运石之门")).toBeTruthy());
    const hs = Array.from(container.querySelectorAll(".wd-chapter-title")).map((h) => h.textContent);
    const order = ["这个世界", "我与它", "相遇纪事", "我的记忆"];
    const idx = order.map((t) => hs.indexOf(t));
    expect(idx.every((v, i) => v !== -1 && (i === 0 || v > idx[i - 1]))).toBe(true);
  });

  it("composer 提交仍调用 createDirectMemory（POST /items/{id}/memories）", async () => {
    mockFetch();
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("命运石之门")).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText(/写一句此刻的感想/), { target: { value: "今天很平静" } });
    fireEvent.click(screen.getByText("记录这一刻"));
    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/items/1/memories"),
        expect.objectContaining({ method: "POST" })
      )
    );
  });

  it("文字记录成功：显示「已留下这一刻」并清空输入", async () => {
    mockFetch();
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("命运石之门")).toBeTruthy());
    const input = screen.getByPlaceholderText(/写一句此刻的感想/);
    fireEvent.change(input, { target: { value: "今天很平静" } });
    fireEvent.click(screen.getByText("记录这一刻"));
    await waitFor(() => expect(screen.getByText("已留下这一刻")).toBeTruthy());
    expect(input.value).toBe(""); // 成功后清空
  });

  it("文字记录失败：安静错误反馈且输入保留", async () => {
    global.fetch = vi.fn((url, opts = {}) => {
      const u = String(url);
      const m = opts.method || "GET";
      if (u.includes("/items/1/detail")) return Promise.resolve({ ok: true, json: () => Promise.resolve({ id: 1, title: "X", source: "bangumi", characters: [], tags: [], description: "" }) });
      if (u.includes("/items/1/memories") && m === "POST") return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "记录失败" }) });
      if (u.includes("/items/1/memories")) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (u.includes("/items/1/reviews")) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("X")).toBeTruthy());
    const input = screen.getByPlaceholderText(/写一句此刻的感想/);
    fireEvent.change(input, { target: { value: "要保留的文字" } });
    fireEvent.click(screen.getByText("记录这一刻"));
    await waitFor(() => expect(screen.getByText("记录失败")).toBeTruthy());
    expect(input.value).toBe("要保留的文字"); // 失败不丢输入
  });

  it("完成/重新打开仍提交（POST /items/{id}/memories，milestone）", async () => {
    mockFetch();
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("命运石之门")).toBeTruthy());
    fireEvent.click(screen.getByText("✓ 完成了"));
    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/items/1/memories"),
        expect.objectContaining({ method: "POST" })
      )
    );
  });
});

describe("默认主题渲染（ADR 0059 起仅保留编目抽屉一套）", () => {
  it("时间轴与双栏结构在默认主题下正常渲染", async () => {
    applyTheme("default");
    mockFetch();
    const { container } = render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("神作")).toBeTruthy());
    // 时间轴点使用 token 值（--accent）
    const dot = container.querySelector(".relative.pl-5 span.rounded-full");
    expect(dot.style.backgroundColor).toBe("var(--accent)");
    cleanup();
  });
});
