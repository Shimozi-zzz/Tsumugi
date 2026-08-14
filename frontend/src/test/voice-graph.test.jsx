// 声优图谱（ADR 0036：搜索驱动的"以人为中心"邻域视图）：
// 搜索过滤 / 邻域渲染（节点远小于全局）/ 角色墙跳转邻域 / 概览模式入口
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import React from "react";
import VoiceGraphView from "../components/VoiceGraphView.jsx";
import { buildCommands } from "../commands.js";

function ok(payload, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(payload) });
}

const DATA = {
  works: [
    { item_id: 1, title: "作品甲", image_url: null, source: "fake" },
    { item_id: 2, title: "作品乙", image_url: null, source: "fake" },
    { item_id: 3, title: "作品丙", image_url: null, source: "fake" },
  ],
  actors: [
    { name: "声优甲", work_count: 4, role_count: 4,
      works: [{ item_id: 1, title: "作品甲", roles: ["角色X", "角色A"] }, { item_id: 2, title: "作品乙", roles: ["角色Y"] }] },
    { name: "声优乙", work_count: 3, role_count: 3,
      works: [{ item_id: 1, title: "作品甲", roles: ["角色Z"] }, { item_id: 3, title: "作品丙", roles: ["角色B"] }] },
    { name: "声优丙", work_count: 3, role_count: 3,
      works: [{ item_id: 2, title: "作品乙", roles: ["角色W"] }, { item_id: 3, title: "作品丙", roles: ["角色C"] }] },
  ],
  stats: { actor_count: 3, work_count: 3, missing_actor_chars: 0 },
};

function svgTexts(container) {
  return [...container.querySelectorAll("svg text")].map((t) => t.textContent);
}
function clickSvgText(container, text) {
  const el = [...container.querySelectorAll("svg text")].find((t) => t.textContent === text);
  if (el) fireEvent.click(el);
  return !!el;
}
function svgTitles(container) {
  return [...container.querySelectorAll("svg circle title")].map((t) => t.textContent || "");
}

function mockFetch() {
  global.fetch = vi.fn((url) => {
    if (String(url).includes("/voice-relations")) return ok(DATA);
    return ok({});
  });
}
function renderGraph(props = {}) {
  const onOpenWork = vi.fn();
  const utils = render(<VoiceGraphView focusActor={props.focusActor ?? null} onOpenWork={onOpenWork} />);
  return { ...utils, onOpenWork };
}

beforeEach(() => { localStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("声优图谱（ADR 0036 邻域视图）", () => {
  it("默认=搜索引导态：不渲染全局图，显示引导文案 + 快捷入口", async () => {
    mockFetch();
    const { container } = renderGraph();
    await waitFor(() => expect(screen.getByText(/搜索一个声优开始探索/)).toBeTruthy());
    expect(screen.getByText(/配音作品最多的声优/)).toBeTruthy();
    expect(screen.queryByText(/全局概览/)).toBeNull(); // 默认不是全局图
    expect(container.querySelectorAll("svg[aria-label='声优邻域关系图']").length).toBe(0);
    expect(screen.getByRole("button", { name: /声优甲/ })).toBeTruthy(); // 快捷入口
  });

  it("搜索过滤：输入名字显示匹配声优，无匹配显示空状态", async () => {
    mockFetch();
    renderGraph();
    await waitFor(() => expect(screen.getByRole("button", { name: /声优甲/ })).toBeTruthy());
    const input = document.querySelector("input[placeholder*='搜索声优']");
    fireEvent.change(input, { target: { value: "声优乙" } });
    await waitFor(() => expect(screen.getByRole("button", { name: /声优乙/ })).toBeTruthy());
    expect(screen.queryByRole("button", { name: /声优丙/ })).toBeNull(); // 过滤掉了
    fireEvent.change(input, { target: { value: "不存在的声优zzz" } });
    await waitFor(() => expect(screen.getByText(/没有匹配「不存在的声优zzz」的声优/)).toBeTruthy());
  });

  it("选中声优 → 邻域视图：只渲染该声优的作品/角色/共同出演，节点远小于全局", async () => {
    mockFetch();
    const { container, onOpenWork } = renderGraph();
    await waitFor(() => expect(screen.getByRole("button", { name: /声优甲/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /声优甲/ }));
    await waitFor(() => expect(container.querySelectorAll("svg[aria-label='声优邻域关系图']").length).toBe(1));
    const texts = svgTexts(container);
    expect(texts).toContain("声优甲"); // 中心声优
    expect(texts).toContain("作品甲");
    expect(texts).toContain("作品乙");
    expect(texts).not.toContain("作品丙"); // 声优甲没配过作品丙 → 不进邻域
    // 共同出演的外环声优（通过 title 可 hover 得知）
    const titles = svgTitles(container).join("|");
    expect(titles).toContain("声优乙");
    expect(titles).toContain("声优丙");
    // 邻域节点数远小于全局概览（1中心 + 2作品 + 3角色 + 2共同出演 ≈ 8）
    const egoCircles = container.querySelectorAll("svg[aria-label='声优邻域关系图'] circle").length;
    expect(egoCircles).toBeLessThanOrEqual(10);
    // 点作品 → 复用主从视图
    expect(clickSvgText(container, "作品甲")).toBe(true);
    expect(onOpenWork).toHaveBeenCalledWith(1);
  });

  it("从角色墙跳转（focusActor）→ 直接进入该声优邻域视图", async () => {
    mockFetch();
    const { container } = renderGraph({ focusActor: "声优乙" });
    await waitFor(() => expect(container.querySelectorAll("svg[aria-label='声优邻域关系图']").length).toBe(1));
    const texts = svgTexts(container);
    expect(texts).toContain("声优乙");
    expect(texts).toContain("作品甲");
    expect(texts).toContain("作品丙");
    expect(texts).not.toContain("作品乙"); // 声优乙没配过作品乙
  });

  it("概览模式入口：主动进入，提示数据量大并渲染全局图（节点更多）", async () => {
    mockFetch();
    const { container } = renderGraph();
    await waitFor(() => expect(screen.getByRole("button", { name: /声优甲/ })).toBeTruthy());
    fireEvent.click(screen.getByText("查看全部声优网络"));
    await waitFor(() => expect(screen.getByText(/全局概览：同时渲染/)).toBeTruthy());
    expect(screen.getByText(/数据量大、边密集/)).toBeTruthy();
    const overview = container.querySelector("svg[aria-label='声优全局概览']");
    expect(overview).toBeTruthy();
    // 全局图包含声优甲没配过的作品丙，且节点数多于邻域
    const texts = svgTexts(container);
    expect(texts).toContain("作品丙");
    expect(overview.querySelectorAll("circle").length).toBeGreaterThan(8);
  });

  describe("Phase 8-2-A：Voice Graph 节点可访问性", () => {
    async function enterEgo(container) {
      await waitFor(() => expect(screen.getByRole("button", { name: /声优甲/ })).toBeTruthy());
      fireEvent.click(screen.getByRole("button", { name: /声优甲/ }));
      await waitFor(() => expect(container.querySelectorAll("svg[aria-label='声优邻域关系图']").length).toBe(1));
    }

    it("可交互节点具备键盘语义：role=button + tabindex=0 + 非空 aria-label（作品与声优）", async () => {
      mockFetch();
      const { container } = renderGraph();
      await enterEgo(container);
      const interactive = container.querySelectorAll('svg[aria-label="声优邻域关系图"] [role="button"]');
      expect(interactive.length).toBeGreaterThan(0);
      const works = container.querySelectorAll('svg[aria-label="声优邻域关系图"] g[aria-label="作品甲"]');
      expect(works.length).toBe(1);
      const work = works[0];
      expect(work.getAttribute("role")).toBe("button");
      expect(work.getAttribute("tabindex")).toBe("0");
      expect(work.getAttribute("aria-label")).toBe("作品甲");
      // 共同出演声优节点也有语义
      const actors = container.querySelectorAll('svg[aria-label="声优邻域关系图"] g[role="button"][aria-label^="声优："]');
      expect(actors.length).toBeGreaterThan(0);
      // 全部可交互节点都有 accessible name
      for (const n of interactive) expect(n.getAttribute("aria-label") || "").not.toBe("");
    });

    it("Enter 激活作品节点 = 与鼠标 click 相同业务结果（onOpenWork）", async () => {
      mockFetch();
      const { container, onOpenWork } = renderGraph();
      await enterEgo(container);
      const work = container.querySelector('svg[aria-label="声优邻域关系图"] g[aria-label="作品甲"]');
      fireEvent.keyDown(work, { key: "Enter" });
      expect(onOpenWork).toHaveBeenCalledWith(1);
      expect(onOpenWork).toHaveBeenCalledTimes(1); // 键盘不额外触发 click
    });

    it("Space 激活作品节点 = 与鼠标 click 相同业务结果（onOpenWork）", async () => {
      mockFetch();
      const { container, onOpenWork } = renderGraph();
      await enterEgo(container);
      const work = container.querySelector('svg[aria-label="声优邻域关系图"] g[aria-label="作品乙"]');
      fireEvent.keyDown(work, { key: " " });
      expect(onOpenWork).toHaveBeenCalledWith(2);
      expect(onOpenWork).toHaveBeenCalledTimes(1);
    });

    it("Enter 激活声优节点 = 进入该声优邻域（与鼠标 click 相同）", async () => {
      mockFetch();
      const { container } = renderGraph();
      await enterEgo(container);
      // 从声优甲邻域，用 Enter 激活共同出演声优乙 → 中心切换为声优乙
      const coActor = container.querySelector('svg[aria-label="声优邻域关系图"] g[role="button"][aria-label="声优：声优乙"]');
      fireEvent.keyDown(coActor, { key: "Enter" });
      await waitFor(() => expect(container.querySelectorAll("svg[aria-label='声优邻域关系图']").length).toBe(1));
      const texts = svgTexts(container);
      expect(texts).toContain("声优乙");
      expect(texts).toContain("作品丙");
      expect(texts).not.toContain("作品乙"); // 声优乙没配过作品乙
    });

    it("不可交互 SVG 元素未被标记为可交互（中心节点/连线无 role=button）", async () => {
      mockFetch();
      const { container } = renderGraph();
      await enterEgo(container);
      const svg = container.querySelector('svg[aria-label="声优邻域关系图"]');
      // 中心声优（r=26）无 role/tabindex
      const center = svg.querySelector('circle[r="26"]');
      expect(center.getAttribute("role")).toBeNull();
      expect(center.getAttribute("tabindex")).toBeNull();
      // 连线 line 无 role/tabindex
      const lines = svg.querySelectorAll("line");
      expect(lines.length).toBeGreaterThan(0);
      for (const l of lines) {
        expect(l.getAttribute("role")).toBeNull();
        expect(l.getAttribute("tabindex")).toBeNull();
      }
    });

    it("鼠标 click 行为保持不变（既有作品点击仍触发 onOpenWork）", async () => {
      mockFetch();
      const { container, onOpenWork } = renderGraph();
      await enterEgo(container);
      expect(clickSvgText(container, "作品甲")).toBe(true);
      expect(onOpenWork).toHaveBeenCalledWith(1);
    });
  });
});

describe("命令面板动作项", () => {
  it("注册表含『打开声优图谱』并调用 ctx.openVoiceGraph", () => {
    const ctx = { openVoiceGraph: vi.fn(), section: vi.fn() };
    const cmds = buildCommands(ctx);
    const voice = cmds.find((c) => c.title === "打开声优图谱");
    expect(voice).toBeTruthy();
    voice.run();
    expect(ctx.openVoiceGraph).toHaveBeenCalled();
  });
});
