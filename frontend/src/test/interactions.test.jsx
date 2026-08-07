// 交互打磨：toast、批量选择、右键菜单、键盘快捷键
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup, within } from "@testing-library/react";
import React from "react";
import { toast, subscribeToast, clearToasts, getToasts } from "../toast.js";
import ToastHost from "../components/ToastHost.jsx";
import DesktopView from "../components/DesktopView.jsx";

function ok(payload, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(payload) });
}

const ITEMS = [
  { id: 1, title: "笔记甲", type: "note", source: "local", tags: [], content: "甲内容", image_url: null, file_path: null, chunks_count: 1 },
  { id: 2, title: "笔记乙", type: "note", source: "local", tags: [], content: "乙内容", image_url: null, file_path: null, chunks_count: 1 },
  { id: 3, title: "笔记丙", type: "note", source: "local", tags: [], content: "丙内容", image_url: null, file_path: null, chunks_count: 1 },
];

function mockFetch(calls) {
  global.fetch = vi.fn((url, opts = {}) => {
    const u = String(url);
    const method = opts.method || "GET";
    if (u.includes("/items/batch/tags")) return ok({ updated: 2, requested: 2 });
    if (u.includes("/items/batch/delete")) return ok({ deleted: 2 });
    if (u.includes("/items") && method === "GET") return ok({ total: ITEMS.length, items: ITEMS });
    if (u.includes("/tags")) return ok([{ id: 1, name: "x", count: 0 }]);
    if (u.includes("/connectors")) return ok([]);
    return ok({});
  });
}

const PROPS = {
  items: [], total: 0, allTags: [], refresh: () => {},
  theme: "default", setTheme: () => {},
  custom: { accentHue: 0, density: "comfortable", radius: 16 }, updateCustom: () => {},
  textOverlays: [], updateTextOverlays: () => {},
};

async function openLibrary() {
  fireEvent.click(screen.getByTitle("图书馆"));
  await waitFor(() => expect(screen.getByTitle("网格视图")).toBeTruthy());
  await waitFor(() => expect(screen.getByText("笔记甲")).toBeTruthy());
}

beforeEach(() => {
  localStorage.clear();
  clearToasts();
});
afterEach(() => {
  vi.useRealTimers();
  cleanup();
  vi.restoreAllMocks();
});

describe("Toast", () => {
  it("toast.success 渲染成功提示", async () => {
    render(<ToastHost />);
    toast.success("导入成功");
    expect(await screen.findByText("导入成功")).toBeTruthy();
  });

  it("自动消失（短时长）", async () => {
    render(<ToastHost />);
    toast.success("短提示", 60);
    expect(await screen.findByText("短提示")).toBeTruthy();
    await waitFor(() => expect(screen.queryByText("短提示")).toBeNull(), { timeout: 2000 });
  });

  it("toast.error 与 toast.info 类型不同", () => {
    clearToasts();
    toast.error("出错了");
    toast.info("提示");
    expect(getToasts().map((t) => t.type)).toEqual(["error", "info"]);
  });
});

describe("批量选择", () => {
  it("进入选择模式 → 点选条目 → 批量栏显示计数 → 打标签触发批量接口", async () => {
    mockFetch();
    render(<DesktopView {...PROPS} />);
    await openLibrary();
    fireEvent.click(screen.getByText("选择"));
    // 选择两条
    fireEvent.click(screen.getByText("笔记甲"));
    fireEvent.click(screen.getByText("笔记乙"));
    await waitFor(() => expect(screen.getByText("已选中 2 项")).toBeTruthy());
    // 打开标签弹层并应用
    fireEvent.click(screen.getByText("打标签"));
    await waitFor(() => expect(screen.getByPlaceholderText(/标签，用逗号分隔/)).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText(/标签，用逗号分隔/), { target: { value: "动漫,恋爱" } });
    fireEvent.click(screen.getByText("应用"));
    await waitFor(() => {
      const post = global.fetch.mock.calls.find(([u, o]) => String(u).includes("/items/batch/tags"));
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body)).toEqual({ item_ids: [1, 2], tag_names: ["动漫", "恋爱"], mode: "add" });
    });
    // 打标签成功 toast
    await waitFor(() => expect(screen.getByText(/已添加标签/)).toBeTruthy());
  });

  it("批量删除需确认，确认后调用批量删除接口", async () => {
    mockFetch();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<DesktopView {...PROPS} />);
    await openLibrary();
    fireEvent.click(screen.getByText("选择"));
    fireEvent.click(screen.getByText("笔记甲"));
    fireEvent.click(screen.getByText("笔记乙"));
    const bar = await screen.findByTestId("batch-bar");
    await waitFor(() => expect(within(bar).getByText("已选中 2 项")).toBeTruthy());
    fireEvent.click(within(bar).getByText("删除"));
    await waitFor(() => {
      const post = global.fetch.mock.calls.find(([u, o]) => String(u).includes("/items/batch/delete"));
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body)).toEqual({ item_ids: [1, 2] });
    });
    await waitFor(() => expect(screen.getByText("已删除 2 项")).toBeTruthy());
  });

  it("Esc 退出选择模式", async () => {
    mockFetch();
    render(<DesktopView {...PROPS} />);
    await openLibrary();
    fireEvent.click(screen.getByText("选择"));
    await waitFor(() => expect(screen.getByText("已选中 0 项")).toBeTruthy());
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText(/已选中/)).toBeNull());
  });
});

describe("右键上下文菜单", () => {
  it("右键条目弹出菜单，Esc 关闭", async () => {
    mockFetch();
    render(<DesktopView {...PROPS} />);
    await openLibrary();
    fireEvent.contextMenu(screen.getByText("笔记甲"));
    const menu = await screen.findByTestId("context-menu");
    expect(within(menu).getByText("查看详情")).toBeTruthy();
    expect(within(menu).getByText("编辑标签")).toBeTruthy();
    expect(within(menu).getByText("写读后感")).toBeTruthy();
    expect(within(menu).getByText("生成安利卡")).toBeTruthy();
    expect(within(menu).getByText("删除")).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("context-menu")).toBeNull());
  });

  it("菜单里删除 → 确认后调用单条删除", async () => {
    mockFetch();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<DesktopView {...PROPS} />);
    await openLibrary();
    fireEvent.contextMenu(screen.getByText("笔记甲"));
    const menu = await screen.findByTestId("context-menu");
    fireEvent.click(within(menu).getByText("删除"));
    await waitFor(() => {
      const del = global.fetch.mock.calls.find(([u, o]) => String(u).endsWith("/items/1") && (o?.method || "GET") === "DELETE");
      expect(del).toBeTruthy();
    });
    await waitFor(() => expect(screen.getByText("已删除")).toBeTruthy());
  });
});

describe("键盘快捷键", () => {
  it("按 ? 打开快捷键说明，Esc 关闭", async () => {
    mockFetch();
    render(<DesktopView {...PROPS} />);
    fireEvent.keyDown(window, { key: "?" });
    await waitFor(() => expect(screen.getByText("键盘快捷键")).toBeTruthy());
    expect(screen.getAllByText("聚焦搜索框并提问").length).toBeGreaterThanOrEqual(1);
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText("键盘快捷键")).toBeNull());
  });

  it("Ctrl+K 聚焦问答搜索框", async () => {
    mockFetch();
    render(<DesktopView {...PROPS} />);
    const input = screen.getByPlaceholderText(/搜索知识库并提问/);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    await waitFor(() => expect(document.activeElement).toBe(input));
  });

  it("点击导航栏帮助按钮也能打开快捷键说明", async () => {
    mockFetch();
    render(<DesktopView {...PROPS} />);
    fireEvent.click(screen.getByTitle("快捷键 (?)"));
    await waitFor(() => expect(screen.getByText("键盘快捷键")).toBeTruthy());
  });
});
