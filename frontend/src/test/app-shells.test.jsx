// ADR 0057：应用外壳三个空间结构方向（A 卡片抽屉 / B 书脊索引 / C 非对称档案室）+ 开关
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import React from "react";
import { ShellA, ShellB, ShellC, ShellSwitcher, SHELL_CONCEPTS, parseShell } from "../components/AppShells.jsx";

function ok(payload, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(payload) });
}

function mockFetch(items = []) {
  global.fetch = vi.fn((url) => {
    const u = String(url);
    if (u.includes("/items") && !u.includes("/detail")) return ok({ total: items.length, items });
    if (u.includes("/search/my")) return ok({ works: [], reviews: [], memories: [] });
    if (u.includes("/memories")) return ok([]);
    if (u.includes("/characters")) return ok({ characters: [] });
    if (u.includes("/voice-relations")) return ok({ works: [], actors: [], stats: { actor_count: 0, work_count: 0, missing_actor_chars: 0 } });
    return ok({});
  });
}

const ITEMS = [
  { id: 3, title: "命运石之门", type: "external_ref", source: "bangumi", chunks_count: 1 },
  { id: 5, title: "日常", type: "external_ref", source: "moegirl", chunks_count: 1 },
];

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("三个外壳结构", () => {
  it("A 卡片抽屉：data-shell=a，含抽屉式导航与抽屉索引", async () => {
    mockFetch(ITEMS);
    const { container } = render(<ShellA />);
    expect(container.querySelector('[data-shell="a"]')).toBeTruthy();
    expect(container.querySelector(".shell-a-cabinet")).toBeTruthy();
    expect(container.querySelector(".shell-a-drawer")).toBeTruthy();
    // 书库真实数据渲染
    await waitFor(() => expect(screen.getByText("命运石之门")).toBeTruthy());
    // 抽屉可切换
    fireEvent.click(screen.getByText("检索台"));
    await waitFor(() => expect(screen.getByPlaceholderText(/检索台/)).toBeTruthy());
  });

  it("B 书脊索引：data-shell=b，导航是一排书脊（竖排文字）", async () => {
    mockFetch(ITEMS);
    const { container } = render(<ShellB />);
    expect(container.querySelector('[data-shell="b"]')).toBeTruthy();
    const spines = container.querySelectorAll(".shell-b-spine");
    expect(spines.length).toBeGreaterThanOrEqual(6);
    const text = container.querySelector(".shell-b-text");
    expect(text).toBeTruthy();
    await waitFor(() => expect(screen.getByText("命运石之门")).toBeTruthy());
  });

  it("C 非对称档案室：data-shell=c，不同房间布局参数不同", async () => {
    mockFetch(ITEMS);
    const { container } = render(<ShellC />);
    expect(container.querySelector('[data-shell="c"]')).toBeTruthy();
    expect(container.querySelector('.shell-c-room[data-room="library"]')).toBeTruthy();
    // 切到记忆回廊 → 房间 data-room 变化（格局不同）
    fireEvent.click(screen.getByText("记忆回廊"));
    await waitFor(() => expect(container.querySelector('.shell-c-room[data-room="gallery"]')).toBeTruthy());
  });

  it("三外壳 data-shell 标注不同（互相不同结构）", () => {
    mockFetch(ITEMS);
    const a = render(<ShellA />);
    expect(a.container.querySelector('[data-shell="a"]')).toBeTruthy();
    cleanup();
    const b = render(<ShellB />);
    expect(b.container.querySelector('[data-shell="b"]')).toBeTruthy();
  });
});

describe("外壳开关", () => {
  it("渲染 4 项 + onChange；parseShell 校验", () => {
    const onChange = vi.fn();
    render(<ShellSwitcher value="classic" onChange={onChange} />);
    expect(SHELL_CONCEPTS.length).toBe(4);
    fireEvent.click(screen.getByText("B 书脊索引"));
    expect(onChange).toHaveBeenCalledWith("b");
    expect(parseShell("a")).toBe("a");
    expect(parseShell("x")).toBeNull();
  });
});
