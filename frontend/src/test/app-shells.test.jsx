// ADR 0057/0059/0064：保留的外壳（经典三栏 + C 非对称档案室）+ 交互化 + 设置内切换
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import React from "react";
import { ShellC, ShellSwitcher, SHELL_CONCEPTS, parseShell } from "../components/AppShells.jsx";

function ok(payload, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(payload) });
}

function mockFetch(items = [], search = { works: [], reviews: [], memories: [] }) {
  global.fetch = vi.fn((url) => {
    const u = String(url);
    if (u.includes("/search/my")) return ok(search);
    if (u.includes("/memories")) return ok([]);
    if (u.includes("/reviews")) return ok([]);
    if (u.includes("/detail")) return ok({ id: items[0]?.id, title: items[0]?.title || "", source: "bangumi", description: "简介", rating: 8.9, tags: [], characters: [], image_url: null, file_path: null, raw_metadata: null, social: {} });
    if (u.includes("/items")) return ok({ total: items.length, items });
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

  it("C 外壳交互化：点书库卡片 → 打开作品详情弹层（可关闭）", async () => {
    mockFetch(ITEMS);
    render(<ShellC />);
    await waitFor(() => expect(screen.getByText("命运石之门")).toBeTruthy());
    fireEvent.click(screen.getByText("命运石之门"));
    await waitFor(() => expect(screen.getByText("作品档案")).toBeTruthy());
    expect(screen.getByText("外部世界")).toBeTruthy();
    fireEvent.click(screen.getByTitle("关闭"));
    await waitFor(() => expect(screen.queryByText("作品档案")).toBeNull());
  });

  it("C 外壳交互化：检索台命中可点开记忆弹层", async () => {
    mockFetch(ITEMS, { works: [], reviews: [], memories: [{ id: 5, item_id: 3, item_title: "命运石之门", source_type: "text", source_ref: null, summary: "今天重看，还是很感动", occurred_at: "2026-08-01T10:00:00", created_at: "2026-08-01T10:00:00" }] });
    render(<ShellC />);
    fireEvent.click(screen.getByText("检索台"));
    const input = screen.getByPlaceholderText(/检索台/);
    fireEvent.change(input, { target: { value: "感动" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(screen.getByText("今天重看，还是很感动")).toBeTruthy());
    fireEvent.click(screen.getByText("今天重看，还是很感动"));
    await waitFor(() => {
      const doc = document.querySelector(".doc");
      expect(doc && doc.textContent).toContain("今天重看");
    });
  });

  it("C 外壳：管理室提供外壳切换入口（ADR 0064，设置内切换）", async () => {
    const onChange = vi.fn();
    mockFetch(ITEMS);
    render(<ShellC shellValue="c" onShellChange={onChange} />);
    fireEvent.click(screen.getByText("管理室"));
    await waitFor(() => expect(screen.getByText("应用外壳")).toBeTruthy());
    fireEvent.click(screen.getByText("经典三栏"));
    expect(onChange).toHaveBeenCalledWith("classic");
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
