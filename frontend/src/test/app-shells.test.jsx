// ADR 0057/0059：保留的外壳（经典三栏 + C 非对称档案室）+ 开关
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import React from "react";
import { ShellC, ShellSwitcher, SHELL_CONCEPTS, parseShell } from "../components/AppShells.jsx";

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

describe("保留的外壳结构", () => {
  it("C 非对称档案室：data-shell=c，不同房间布局参数不同", async () => {
    mockFetch(ITEMS);
    const { container } = render(<ShellC />);
    expect(container.querySelector('[data-shell="c"]')).toBeTruthy();
    expect(container.querySelector('.shell-c-room[data-room="library"]')).toBeTruthy();
    // 切到记忆回廊 → 房间 data-room 变化（格局不同）
    fireEvent.click(screen.getByText("记忆回廊"));
    await waitFor(() => expect(container.querySelector('.shell-c-room[data-room="gallery"]')).toBeTruthy());
  });
});

describe("外壳开关", () => {
  it("渲染 2 项（经典三栏 + C）+ onChange；parseShell 校验", () => {
    const onChange = vi.fn();
    render(<ShellSwitcher value="classic" onChange={onChange} />);
    expect(SHELL_CONCEPTS.length).toBe(2);
    fireEvent.click(screen.getByText("C 非对称档案室"));
    expect(onChange).toHaveBeenCalledWith("c");
    expect(parseShell("c")).toBe("c");
    expect(parseShell("a")).toBeNull(); // A/B 已移除
    expect(parseShell("b")).toBeNull();
  });
});
