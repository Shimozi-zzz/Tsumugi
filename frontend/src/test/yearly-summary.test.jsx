// 年度总结（ADR 0033）：热力图渲染/悬停详情/档位配色/命令面板动作项
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import React from "react";
import YearlySummary from "../components/YearlySummary.jsx";
import { buildCommands } from "../commands.js";

function ok(payload, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(payload) });
}

const DATA = {
  year: 2026,
  days: [
    { date: "2026-08-07", reviews: 57, collections: 57, score: 171 },
    { date: "2026-08-08", reviews: 0, collections: 4, score: 4 },
  ],
  stats: { total_reviews: 57, total_collections: 61, total_score: 175, active_days: 2, busiest_month: "2026-08", longest_streak: 1 },
  weights: { review: 2, collection: 1 },
};

function mockFetch() {
  global.fetch = vi.fn((url) => {
    if (String(url).includes("/activity")) return ok(DATA);
    return ok({});
  });
}

beforeEach(() => { localStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("YearlySummary（年度热力图）", () => {
  it("渲染热力图 SVG + 统计摘要（收藏/书评/活跃天数/最长连续）", async () => {
    mockFetch();
    const { container } = render(<YearlySummary year={2026} />);
    await waitFor(() => expect(container.querySelector("svg[aria-label*='热力图']")).toBeTruthy());
    expect(container.querySelectorAll("svg rect").length).toBeGreaterThan(50); // 年度网格
    expect(screen.getByText("61")).toBeTruthy();  // 全年收藏
    expect(screen.getByText("57")).toBeTruthy();  // 书评总数
    expect(screen.getByText(/活跃度 = 书评×2 \+ 收藏×1/)).toBeTruthy();
    expect(screen.getByText("2026-08")).toBeTruthy(); // 最活跃月份值
  });

  it("悬停（title）显示当天具体数据：X 条书评 · Y 个收藏", async () => {
    mockFetch();
    const { container } = render(<YearlySummary year={2026} />);
    await waitFor(() => expect(container.querySelector("svg rect title")).toBeTruthy());
    const titles = [...container.querySelectorAll("svg rect title")].map((t) => t.textContent);
    expect(titles.some((t) => t.includes("57 条书评 · 57 个收藏"))).toBe(true);
    expect(titles.some((t) => t.includes("0 条书评 · 4 个收藏"))).toBe(true);
  });

  it("档位配色：高分天用 accent 高透明度（level4=70%，克制收敛），零分天用 surface-2", async () => {
    mockFetch();
    const { container } = render(<YearlySummary year={2026} />);
    await waitFor(() => expect(container.querySelectorAll("svg rect").length).toBeGreaterThan(0));
    const rects = [...container.querySelectorAll("svg rect")];
    const high = rects.find((r) => r.querySelector("title")?.textContent.includes("57 条书评"));
    const low = rects.find((r) => r.querySelector("title")?.textContent.includes("2026 年 1 月 2 日") || r.getAttribute("fill") === "var(--surface-2)");
    expect(high.getAttribute("fill")).toContain("70%");
    expect(low.getAttribute("fill")).toBe("var(--surface-2)");
  });
});

describe("命令面板动作项", () => {
  it("注册表含『打开年度总结』并调用 ctx.openSummary", () => {
    const ctx = { openSummary: vi.fn(), section: vi.fn() };
    const cmds = buildCommands(ctx);
    const cmd = cmds.find((c) => c.title === "打开年度总结");
    expect(cmd).toBeTruthy();
    expect(cmd.keywords.some((k) => k.includes("热力图"))).toBe(true);
    cmd.run();
    expect(ctx.openSummary).toHaveBeenCalled();
  });
});
