// 声优图谱（ADR 0032）：图谱渲染、阈值过滤、节点点击跳转、focusActor 自动选中、命令面板动作项
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
    { name: "声优甲", work_count: 2, role_count: 2,
      works: [{ item_id: 1, title: "作品甲", roles: ["角色X"] }, { item_id: 2, title: "作品乙", roles: ["角色Y"] }] },
    { name: "声优独", work_count: 1, role_count: 1,
      works: [{ item_id: 1, title: "作品甲", roles: ["角色Z"] }] },
  ],
  stats: { actor_count: 2, work_count: 2, missing_actor_chars: 0 },
};

function mockFetch() {
  global.fetch = vi.fn((url) => {
    if (String(url).includes("/voice-relations")) return ok(DATA);
    return ok({});
  });
}

function renderGraph(props = {}) {
  const onOpenWork = vi.fn();
  render(<VoiceGraphView focusActor={props.focusActor ?? null} onOpenWork={onOpenWork} />);
  return onOpenWork;
}

beforeEach(() => { localStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("VoiceGraphView（声优图谱）", () => {
  it("默认阈值≥2：跨作品声优可见，只配一作的声优被过滤", async () => {
    mockFetch();
    renderGraph();
    await waitFor(() => expect(screen.getByText("声优甲")).toBeTruthy());
    expect(screen.getByText("作品甲")).toBeTruthy(); // 作品节点
    expect(screen.queryByText("声优独")).toBeNull(); // 只配一作 → 默认隐藏
    expect(screen.getByText(/当前：1 声优 \/ 2 作品/)).toBeTruthy();
  });

  it("点击声优 → 展示完整配音列表（作品 → 角色）", async () => {
    mockFetch();
    renderGraph();
    await waitFor(() => screen.getByText("声优甲"));
    fireEvent.click(screen.getByText("声优甲"));
    await waitFor(() => expect(screen.getByText(/配音 2 部作品 · 2 个角色/)).toBeTruthy());
    expect(screen.getByText("「角色X」")).toBeTruthy();
    expect(screen.getByText("「角色Y」")).toBeTruthy();
    expect(screen.getAllByText("作品甲").length).toBeGreaterThanOrEqual(1); // 详情面板里的作品
    expect(screen.getAllByText("作品乙").length).toBeGreaterThanOrEqual(1);
  });

  it("点击作品节点 → onOpenWork(item_id)（复用主从视图）", async () => {
    mockFetch();
    const onOpenWork = renderGraph();
    await waitFor(() => screen.getByText("作品乙"));
    fireEvent.click(screen.getByText("作品乙"));
    expect(onOpenWork).toHaveBeenCalledWith(2);
  });

  it("focusActor → 自动选中并展示该声优配音列表", async () => {
    mockFetch();
    renderGraph({ focusActor: "声优甲" });
    await waitFor(() => expect(screen.getByText(/配音 2 部作品 · 2 个角色/)).toBeTruthy());
    expect(screen.getByText("「角色X」")).toBeTruthy();
  });

  it("阈值调节：调到 3 后，配音作品数=2 的声优也被过滤", async () => {
    mockFetch();
    renderGraph();
    await waitFor(() => screen.getByText("声优甲"));
    fireEvent.click(screen.getByText("3"));
    await waitFor(() => expect(screen.queryByText("声优甲")).toBeNull());
    expect(screen.getByText(/当前：0 声优/)).toBeTruthy();
  });
});

describe("命令面板动作项", () => {
  it("注册表含『打开声优图谱』并调用 ctx.openVoiceGraph", () => {
    const ctx = { ...({} ), openVoiceGraph: vi.fn(), section: vi.fn() };
    const cmds = buildCommands(ctx);
    const voice = cmds.find((c) => c.title === "打开声优图谱");
    expect(voice).toBeTruthy();
    voice.run();
    expect(ctx.openVoiceGraph).toHaveBeenCalled();
  });
});
