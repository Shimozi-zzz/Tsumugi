// 声优图谱（ADR 0032 + 0035）：默认阈值3、标签分级（高连接才有文字）、点击交互、命令面板动作项
// 注意：SVG 文字标签用 <svg text> 精确查询（getByText 会把 <title> 子文本算进父节点，造成误匹配）
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
  ],
  actors: [
    { name: "声优甲", work_count: 5, role_count: 5,
      works: [{ item_id: 1, title: "作品甲", roles: ["角色X", "角色A"] }, { item_id: 2, title: "作品乙", roles: ["角色Y"] }] },
    { name: "声优乙", work_count: 3, role_count: 3,
      works: [{ item_id: 1, title: "作品甲", roles: ["角色Z"] }, { item_id: 2, title: "作品乙", roles: ["角色W"] }] },
    { name: "声优独", work_count: 1, role_count: 1,
      works: [{ item_id: 1, title: "作品甲", roles: ["角色P"] }] },
  ],
  stats: { actor_count: 3, work_count: 2, missing_actor_chars: 0 },
};

function svgTexts(container) {
  return [...container.querySelectorAll("svg text")].map((t) => t.textContent);
}
function clickSvgText(container, text) {
  const el = [...container.querySelectorAll("svg text")].find((t) => t.textContent === text);
  if (el) fireEvent.click(el);
  return !!el;
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

describe("VoiceGraphView（声优图谱）", () => {
  it("默认阈值=3：配音≥3 的声优有节点，只配1作的过滤，且默认选中档位 3", async () => {
    mockFetch();
    const { container } = renderGraph();
    await waitFor(() => expect(container.querySelectorAll("svg text").length).toBeGreaterThan(0));
    const texts = svgTexts(container);
    expect(texts).toContain("声优甲");   // work_count 5
    expect(texts).toContain("作品甲");
    expect(texts).not.toContain("声优独"); // work_count 1 被过滤（只在其 circle <title> 里可 hover 得知）
    expect(screen.getByText(/当前：2 声优 \/ 2 作品/)).toBeTruthy();
    // 默认选中档位是 3（按钮背景 = accent）
    expect(screen.getByText("3").style.backgroundColor).toBe("var(--accent)");
    expect(screen.getByText("2").style.backgroundColor).toBe("var(--surface-2)");
  });

  it("标签分级：高连接声优(≥4)有文字标签，低连接(3)只显示圆点+hover title", async () => {
    mockFetch();
    const { container } = renderGraph();
    await waitFor(() => expect(svgTexts(container)).toContain("声优甲")); // work_count 5 ≥ LABEL_ACTOR_MIN → 有标签
    expect(svgTexts(container)).not.toContain("声优乙");                   // work_count 3 < 4 → 无文字标签
    // 但声优乙的圆点存在，且带 hover title（名称可 hover 得知）
    const titles = [...container.querySelectorAll("svg circle title")].map((t) => t.textContent);
    expect(titles.some((t) => t.includes("声优乙：配音 3 部作品"))).toBe(true);
  });

  it("点击声优 → 展示完整配音列表（作品 → 角色）", async () => {
    mockFetch();
    const { container } = renderGraph();
    await waitFor(() => expect(clickSvgText(container, "声优甲")).toBe(true));
    await waitFor(() => expect(screen.getByText(/配音 5 部作品 · 5 个角色/)).toBeTruthy());
    expect(screen.getByText("「角色X」")).toBeTruthy();
    expect(screen.getAllByText("作品甲").length).toBeGreaterThanOrEqual(1);
  });

  it("点击作品节点 → onOpenWork(item_id)（复用主从视图）", async () => {
    mockFetch();
    const { container, onOpenWork } = renderGraph();
    await waitFor(() => expect(clickSvgText(container, "作品甲")).toBe(true));
    expect(onOpenWork).toHaveBeenCalledWith(1);
  });

  it("focusActor → 自动选中并展示该声优配音列表", async () => {
    mockFetch();
    renderGraph({ focusActor: "声优甲" });
    await waitFor(() => expect(screen.getByText(/配音 5 部作品 · 5 个角色/)).toBeTruthy());
    expect(screen.getByText("「角色Y」")).toBeTruthy();
  });

  it("阈值调节：调到 5 后，配音作品数=3 的声优被过滤", async () => {
    mockFetch();
    const { container } = renderGraph();
    await waitFor(() => expect(svgTexts(container)).toContain("声优甲"));
    fireEvent.click(screen.getByText("5"));
    await waitFor(() => expect(screen.getByText(/当前：1 声优/)).toBeTruthy());
    expect(svgTexts(container)).toContain("声优甲");
    expect(svgTexts(container)).not.toContain("声优乙");
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
