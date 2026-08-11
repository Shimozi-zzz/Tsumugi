// 布局测试：应用外壳（app shell，ADR 0028）
// 核心：主内容区拥有唯一滚动容器；左侧图标导航 + 资料库侧栏 + 顶部标题栏
// 均为固定（不随主内容滚动）。用 DOM 结构 + class + 滚动模拟验证。
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import React from "react";
import DesktopView from "../components/DesktopView.jsx";
import App from "../App.jsx";

function ok(payload, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(payload) });
}

const ITEMS = [
  { id: 1, title: "笔记甲", type: "note", source: "local", tags: [], content: "甲内容", image_url: null, file_path: null, chunks_count: 1 },
  { id: 2, title: "笔记乙", type: "note", source: "local", tags: [], content: "乙内容", image_url: null, file_path: null, chunks_count: 1 },
];

function mockFetch() {
  global.fetch = vi.fn((url, opts = {}) => {
    const u = String(url);
    const m = opts.method || "GET";
    if (u.includes("/items") && m === "GET") return ok({ total: ITEMS.length, items: ITEMS });
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
  fireEvent.click(screen.getByTitle("书库"));
  await waitFor(() => expect(screen.getByTitle("网格视图")).toBeTruthy());
  await waitFor(() => expect(screen.getByText("笔记甲")).toBeTruthy());
}

beforeEach(() => { localStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("应用外壳布局（ADR 0028）", () => {
  it("左侧导航/侧栏是主内容滚动容器的兄弟节点（不随其滚动）", async () => {
    mockFetch();
    render(<DesktopView {...PROPS} />);
    await openLibrary();
    const shell = screen.getByTestId("app-shell");
    const nav = screen.getByTestId("left-nav");
    const aside = screen.getByTestId("left-sidebar");
    const main = screen.getByTestId("main-content");
    // 三者都是 shell 的直接子级（平级兄弟）
    expect(shell.children).toContain(nav);
    expect(shell.children).toContain(aside);
    expect(shell.children).toContain(main);
    // 主内容滚动容器**不包含**侧边栏/导航 → 滚动不可能把它们带走
    expect(main.contains(nav)).toBe(false);
    expect(main.contains(aside)).toBe(false);
  });

  it("shell 固定高度不外溢；主内容拥有独立滚动容器，侧栏有自己的内部滚动", async () => {
    mockFetch();
    render(<DesktopView {...PROPS} />);
    await openLibrary();
    const shell = screen.getByTestId("app-shell");
    const aside = screen.getByTestId("left-sidebar");
    const main = screen.getByTestId("main-content");
    // 外壳：固定视口高度（flex-1 min-h-0），overflow-hidden 阻止整页外溢
    expect(shell.className).toContain("flex-1");
    expect(shell.className).toContain("min-h-0");
    expect(shell.className).toContain("overflow-hidden");
    // 主内容：唯一的滚动容器
    expect(main.className).toContain("overflow-y-auto");
    expect(main.className).toContain("min-h-0");
    // 侧栏内容有独立内部滚动
    const sidebarScroll = aside.querySelector(".overflow-y-auto");
    expect(sidebarScroll).toBeTruthy();
    expect(sidebarScroll.className).toContain("overflow-y-auto");
  });

  it("模拟主内容滚动：侧边栏/导航位置不受影响", async () => {
    mockFetch();
    render(<DesktopView {...PROPS} />);
    await openLibrary();
    const nav = screen.getByTestId("left-nav");
    const aside = screen.getByTestId("left-sidebar");
    const main = screen.getByTestId("main-content");
    // jsdom 无真实布局：固定 nav/aside 的 bounding rect，滚动后断言不变
    const rect = { top: 12, left: 0, height: 600, width: 100 };
    const spyNav = vi.spyOn(nav, "getBoundingClientRect").mockReturnValue(rect);
    const spyAside = vi.spyOn(aside, "getBoundingClientRect").mockReturnValue(rect);
    main.scrollTop = 400;
    fireEvent.scroll(main);
    expect(main.scrollTop).toBe(400); // 滚动确实发生在主内容容器内
    expect(nav.getBoundingClientRect().top).toBe(12);  // 侧边栏纹丝不动
    expect(aside.getBoundingClientRect().top).toBe(12);
    spyNav.mockRestore();
    spyAside.mockRestore();
  });

  it("顶栏（App 壳）固定：app-root 为 h-screen flex-col overflow-hidden，顶栏与内容区平级", async () => {
    mockFetch();
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("app-shell")).toBeTruthy());
    const root = document.querySelector(".app-root");
    expect(root.className).toContain("h-screen");     // 固定视口高度
    expect(root.className).toContain("flex");
    expect(root.className).toContain("flex-col");
    expect(root.className).toContain("overflow-hidden"); // 整页不滚动
    const header = root.querySelector("header");
    expect(root.children[0]).toBe(header);
    expect(header.className).toContain("shrink-0");  // 顶栏不随内容伸缩/滚动
    const shell = screen.getByTestId("app-shell");
    expect(header.nextElementSibling).toBe(shell);   // 顶栏 + 工作区平级，工作区填满剩余高度
  });
});

describe("馆内导览 Shell（ADR 0066 夜书房）", () => {
  it("主导航为馆室列表：serif 馆室 + mono 编号，含检索台/管理室", async () => {
    mockFetch();
    render(<DesktopView {...PROPS} />);
    await waitFor(() => expect(screen.getByTestId("main-content")).toBeTruthy());
    const nav = screen.getByTestId("left-nav");
    // 房间按钮：书库/记忆回廊/时光轴/人物档案/检索台/管理室
    for (const label of ["书库", "记忆回廊", "时光轴", "人物档案", "检索台", "管理室"]) {
      expect(nav.querySelector(`[title="${label}"]`)).toBeTruthy();
    }
    // 移动端底部房间导航存在（默认隐藏）
    expect(screen.getByTestId("room-bottom-bar")).toBeTruthy();
  });

  it("顶栏：当前房间面包屑（serif 房间 / mono 英文）+ 全局检索入口 + Ctrl+K", async () => {
    mockFetch();
    render(<DesktopView {...PROPS} />);
    await waitFor(() => expect(screen.getByTestId("main-content")).toBeTruthy());
    expect(screen.getByText(/检索台 \/ Desk/)).toBeTruthy(); // 默认打开问答=检索台
    expect(screen.getByTitle("全局检索")).toBeTruthy();       // 全局检索入口
    expect(screen.getByTitle("命令面板 (Ctrl+K)")).toBeTruthy();
  });

  it("平板：汉堡呼出馆内导览抽屉，点击房间关闭并切换", async () => {
    mockFetch();
    render(<DesktopView {...PROPS} />);
    await waitFor(() => expect(screen.getByTestId("main-content")).toBeTruthy());
    fireEvent.click(screen.getByTitle("馆内导览"));
    const drawer = document.querySelector(".desk-drawer");
    expect(drawer).toBeTruthy();
    fireEvent.click(drawer.querySelector('[title="书库"]'));
    await waitFor(() => expect(screen.getByTitle("网格视图")).toBeTruthy());
    expect(document.querySelector(".desk-drawer")).toBeNull(); // 抽屉已关闭
  });
});
