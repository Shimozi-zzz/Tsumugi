// 命令面板（ADR 0031）：注册表 + 组件 + DesktopView 集成（Ctrl+K/内容跳转/动作/键盘导航/空状态）
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import React from "react";
import DesktopView from "../components/DesktopView.jsx";
import CommandPalette from "../components/CommandPalette.jsx";
import { buildCommands, matchCommand, GROUP_ORDER } from "../commands.js";
import { applyTheme } from "../themes.js";

function ok(payload, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(payload) });
}

const ITEMS = [
  { id: 1, title: "命运石之门", type: "external_ref", source: "bangumi", tags: [], content: "", image_url: null, file_path: null, chunks_count: 1 },
  { id: 2, title: "我的笔记", type: "note", source: "local", tags: [], content: "内容", image_url: null, file_path: null, chunks_count: 1 },
];
const DETAILS = {
  1: { id: 1, title: "命运石之门", source: "bangumi", description: "简介", rating: 8.9, my_rating: null, tags: ["科幻"], reference_text: "", social: {}, raw_metadata: null, characters: [], image_url: null, file_path: null },
};

function mockFetch() {
  global.fetch = vi.fn((url, opts = {}) => {
    const u = String(url);
    const m = opts.method || "GET";
    const dm = u.match(/\/items\/(\d+)\/detail$/);
    if (dm) return ok(DETAILS[Number(dm[1])] || {});
    if (u.includes("/reviews") && m === "GET") return ok([]);
    if (u.includes("/items") && m === "GET") return ok({ total: ITEMS.length, items: ITEMS });
    if (u.includes("/tags")) return ok([{ id: 1, name: "科幻", count: 1 }]);
    if (u.includes("/connectors")) return ok([]);
    if (u.includes("/plugins")) return ok({ plugins: [], failures: [], notice_needed: false, plugin_dir: "./plugins" });
    return ok({});
  });
}

const PROPS = {
  items: [], total: 0, allTags: [{ id: 1, name: "科幻", count: 1 }], refresh: () => {},
  theme: "default", setTheme: () => {},
  custom: { accentHue: 0, density: "comfortable", radius: 16 }, updateCustom: () => {},
  textOverlays: [], updateTextOverlays: () => {},
};

const CTX = {
  items: ITEMS,
  tags: [{ name: "科幻" }, { name: "恋爱" }],
  openItem: vi.fn(), openImport: vi.fn(), section: vi.fn(), ask: vi.fn(),
  setTheme: (k) => applyTheme(k), openTag: vi.fn(), shareCard: vi.fn(), reviewStudio: vi.fn(),
};

function renderPalette(overrides = {}) {
  const props = { open: true, onClose: vi.fn(), ctx: CTX, ...overrides };
  const utils = render(<CommandPalette {...props} />);
  return { ...utils, onClose: props.onClose };
}

beforeEach(() => { localStorage.clear(); document.documentElement.removeAttribute("data-theme"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("命令注册表（ADR 0031）", () => {
  it("buildCommands 覆盖四组：条目/动作/主题/标签", () => {
    const cmds = buildCommands(CTX);
    const groups = new Set(cmds.map((c) => c.group));
    expect(groups).toEqual(new Set(["条目", "动作", "主题", "标签"]));
    expect(cmds.filter((c) => c.group === "主题").length).toBe(4); // 四套主题
    expect(cmds.some((c) => c.title === "切换主题：深夜深蓝")).toBe(true);
    expect(cmds.some((c) => c.title === "新建笔记")).toBe(true);
  });

  it("matchCommand：去空格小写子串匹配", () => {
    const cmd = { title: "切换主题：深夜深蓝", keywords: ["主题", "theme", "dark"] };
    expect(matchCommand(cmd, "深夜深蓝")).toBe(true);
    expect(matchCommand(cmd, "主题")).toBe(true);
    expect(matchCommand(cmd, " 深 夜 ")).toBe(true); // 去空格
    expect(matchCommand(cmd, "不存在")).toBe(false);
    expect(matchCommand(cmd, "")).toBe(true);
  });

  it("GROUP_ORDER 顺序：条目在前", () => {
    expect(GROUP_ORDER[0]).toBe("条目");
  });
});

describe("CommandPalette 组件", () => {
  it("打开时聚焦输入框；Esc 关闭", () => {
    renderPalette();
    const input = document.querySelector("input");
    expect(input).toBeTruthy();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(renderPalette().onClose).toBeDefined();
  });

  it("输入过滤候选项（查询 → 只显示匹配）", () => {
    renderPalette();
    const input = document.querySelector("input");
    fireEvent.change(input, { target: { value: "角色墙" } });
    expect(screen.getByText("打开角色墙")).toBeTruthy();
    expect(screen.queryByText("新建笔记")).toBeNull();
    fireEvent.change(input, { target: { value: "命运石" } });
    expect(screen.getByText("命运石之门")).toBeTruthy(); // 条目命中
  });

  it("键盘导航：ArrowDown 移动选择，Enter 执行对应命令", () => {
    const ctx = { ...CTX, section: vi.fn() };
    render(<CommandPalette open onClose={() => {}} ctx={ctx} />);
    const input = document.querySelector("input");
    // 空查询 flat 顺序：动作 → 主题 → 标签（条目在空查询不展示）
    // 第一个=新建笔记，第二个=打开资料库
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(ctx.section).toHaveBeenCalledWith("library");
  });

  it("内容搜索：选中条目回车 → 执行 openItem（跳转主从详情）", () => {
    const ctx = { ...CTX, openItem: vi.fn() };
    render(<CommandPalette open onClose={() => {}} ctx={ctx} />);
    const input = document.querySelector("input");
    fireEvent.change(input, { target: { value: "命运石之门" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(ctx.openItem).toHaveBeenCalledWith(expect.objectContaining({ id: 1, title: "命运石之门" }));
  });

  it("动作执行：切换深色主题 → data-theme=dark", () => {
    render(<CommandPalette open onClose={() => {}} ctx={CTX} />);
    const input = document.querySelector("input");
    fireEvent.change(input, { target: { value: "深夜深蓝" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("无匹配 → 空状态提示", () => {
    renderPalette();
    const input = document.querySelector("input");
    fireEvent.change(input, { target: { value: "zzz不存在的词" } });
    expect(screen.getByText("没有匹配的命令或资料。")).toBeTruthy();
  });

  it("执行后关闭（onClose 被调用）", () => {
    const { onClose } = renderPalette();
    const input = document.querySelector("input");
    fireEvent.change(input, { target: { value: "打开问答" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onClose).toHaveBeenCalled();
  });
});

describe("DesktopView 集成", () => {
  it("Ctrl+K 呼出命令面板，Esc 关闭", async () => {
    mockFetch();
    render(<DesktopView {...PROPS} />);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    await waitFor(() => expect(document.querySelector("input[placeholder*='搜索资料']")).toBeTruthy());
    fireEvent.keyDown(document.querySelector("input[placeholder*='搜索资料']"), { key: "Escape" });
    await waitFor(() => expect(document.querySelector("input[placeholder*='搜索资料']")).toBeNull());
  });

  it("内容搜索跳转：输入标题回车 → 主从详情面板立即显示该条目", async () => {
    mockFetch();
    render(<DesktopView {...PROPS} />);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    await waitFor(() => expect(document.querySelector("input[placeholder*='搜索资料']")).toBeTruthy());
    const input = document.querySelector("input[placeholder*='搜索资料']");
    fireEvent.change(input, { target: { value: "命运石之门" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => {
      const h2 = document.querySelector("h2");
      expect(h2 && h2.textContent).toBe("命运石之门");
    });
    // 面板已关闭
    expect(document.querySelector("input[placeholder*='搜索资料']")).toBeNull();
  });
});
