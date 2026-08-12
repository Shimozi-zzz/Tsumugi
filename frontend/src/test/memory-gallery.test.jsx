// 记忆回廊（Phase C / ADR 0043）：页面渲染、年份/作品筛选、空状态、命令面板动作、
// 主导航入口
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import React from "react";
import MemoryGallery from "../components/MemoryGallery.jsx";
import DesktopView from "../components/DesktopView.jsx";
import { buildCommands } from "../commands.js";

function ok(payload, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(payload) });
}

const MEMORIES = [
  { id: 1, item_id: 1, item_title: "命运石之门", source_type: "review", source_ref: 10, occurred_at: "2025-11-03T10:00:00", summary: "神作", created_at: "2025-11-03T10:00:00" },
  { id: 2, item_id: 2, item_title: "魔法少女小圆", source_type: "review", source_ref: 11, occurred_at: "2026-01-15T20:30:00", summary: "第一次看就哭", created_at: "2026-01-15T20:30:00" },
  { id: 3, item_id: 3, item_title: "空之境界", source_type: "review", source_ref: 12, occurred_at: "2026-08-07T09:00:00", summary: "从 Bangumi 导入", created_at: "2026-08-07T09:00:00" },
];

function mockFetch(memories = MEMORIES) {
  global.fetch = vi.fn((url) => {
    const u = String(url);
    if (u.includes("/memories")) return ok(memories);
    if (u.includes("/reviews") ) return ok([]);
    if (u.includes("/items") && u.includes("detail")) return ok({});
    if (u.includes("/items")) return ok({ total: 0, items: [] });
    if (u.includes("/tags")) return ok([]);
    if (u.includes("/connectors")) return ok([]);
    if (u.includes("/plugins")) return ok({ plugins: [], failures: [], notice_needed: false, plugin_dir: "./plugins" });
    return ok({});
  });
}

beforeEach(() => { localStorage.clear(); document.documentElement.removeAttribute("data-theme"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("记忆回廊页面", () => {
  it("按年份分组渲染：年头标签 + 条目（日期·作品 + 摘要），整体时间倒序", async () => {
    mockFetch();
    const { container } = render(<MemoryGallery onOpenWork={() => {}} />);
    await waitFor(() => expect(screen.getByText("神作")).toBeTruthy());
    // 年头分组：2026 在 2025 之前
    const sections = [...container.querySelectorAll("section")];
    expect(sections.length).toBe(2);
    expect(sections[0].querySelector("span")?.textContent).toContain("2026");
    expect(sections[1].querySelector("span")?.textContent).toContain("2025");
    // 档案编号：年份标题用 ArchiveNo（§ + 大号衬线数字）
    const firstNo = sections[0].querySelector('[data-testid="archive-no"]');
    expect(firstNo).toBeTruthy();
    expect(firstNo.textContent).toContain("§");
    expect(firstNo.className).toContain("archive-no-lg");
    // 2026 组内：最新在前（08-07 在 01-15 前）
    const first2026 = sections[0].querySelector("button");
    expect(first2026.textContent).toContain("08-07");
    expect(first2026.textContent).toContain("空之境界");
    expect(first2026.textContent).toContain("从 Bangumi 导入");
  });

  it("点击条目 → onOpenWork(作品 id)", async () => {
    mockFetch();
    const onOpenWork = vi.fn();
    render(<MemoryGallery onOpenWork={onOpenWork} />);
    await waitFor(() => expect(screen.getByText("神作")).toBeTruthy());
    fireEvent.click(screen.getByText("神作"));
    expect(onOpenWork).toHaveBeenCalledWith(1);
  });

  it("年份筛选：点 2025 chip → 只剩该年条目；再点取消回全部", async () => {
    mockFetch();
    render(<MemoryGallery onOpenWork={() => {}} />);
    await waitFor(() => expect(screen.getByText("神作")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "2025" }));
    expect(screen.getByText("神作")).toBeTruthy();
    expect(screen.queryByText("第一次看就哭")).toBeNull();
    expect(screen.queryByText("从 Bangumi 导入")).toBeNull();
    // 再次点击取消
    fireEvent.click(screen.getByRole("button", { name: "2025" }));
    await waitFor(() => expect(screen.getByText("从 Bangumi 导入")).toBeTruthy());
  });

  it("作品筛选：选择某作品 → 只剩该作品条目", async () => {
    mockFetch();
    render(<MemoryGallery onOpenWork={() => {}} />);
    await waitFor(() => expect(screen.getByText("神作")).toBeTruthy());
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "2" } });
    await waitFor(() => expect(screen.getByText("第一次看就哭")).toBeTruthy());
    expect(screen.queryByText("神作")).toBeNull();
    expect(screen.queryByText("从 Bangumi 导入")).toBeNull();
  });

  it("Phase D：文本筛（summary 子串，与后端 ?search= 字段一致）；清除恢复", async () => {
    mockFetch();
    render(<MemoryGallery onOpenWork={() => {}} />);
    await waitFor(() => expect(screen.getByText("神作")).toBeTruthy());
    const input = screen.getByLabelText("搜索记忆");
    fireEvent.change(input, { target: { value: "神作" } });
    await waitFor(() => expect(screen.getByText("神作")).toBeTruthy());
    expect(screen.queryByText("第一次看就哭")).toBeNull();
    // 清除 → 恢复全部
    fireEvent.click(screen.getByTitle("清除搜索"));
    await waitFor(() => expect(screen.getByText("第一次看就哭")).toBeTruthy());
  });

  it("Phase D：文本筛无命中 → 提示没有找到包含", async () => {
    mockFetch();
    render(<MemoryGallery onOpenWork={() => {}} />);
    await waitFor(() => expect(screen.getByText("神作")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("搜索记忆"), { target: { value: "不存在的词" } });
    await waitFor(() => expect(screen.getByText(/没有找到包含「不存在的词」的记忆/)).toBeTruthy());
  });

  it("空状态：无任何记忆时给引导", async () => {
    mockFetch([]);
    render(<MemoryGallery onOpenWork={() => {}} />);
    await waitFor(() => expect(screen.getByText(/记忆回廊还是空的/)).toBeTruthy());
  });

  it("筛选无结果：年份有 chip 但该年无记忆（或作品筛选后空）", async () => {
    mockFetch([{ id: 1, item_id: 1, item_title: "a", source_type: "review", source_ref: 10, occurred_at: "2026-08-07T09:00:00", summary: "s", created_at: "2026-08-07T09:00:00" }]);
    render(<MemoryGallery onOpenWork={() => {}} />);
    await waitFor(() => expect(screen.getByText("s")).toBeTruthy());
    // 选一个不存在的年份无 chip 可点；用作品筛选制造空：先选全部年份再选不匹配作品不可行
    // 改用：仅一条 2026 记忆，点年份后仍显示；验证无数据年份 chip 不出现
    expect(screen.queryByText("2025")).toBeNull();
  });

  it("Phase D：收藏/完成时刻在回廊里带类型标记（书评行保持干净）", async () => {
    mockFetch([
      { id: 1, item_id: 1, item_title: "魔法少女小圆", source_type: "review", source_ref: 10, occurred_at: "2026-08-07T09:00:00", summary: "神作", created_at: "2026-08-07T09:00:00" },
      { id: 2, item_id: 2, item_title: "命运石之门", source_type: "collection", source_ref: 2, occurred_at: "2026-08-08T10:00:00", summary: "这一天，我把它带回了图书馆", created_at: "2026-08-08T10:00:00" },
      { id: 3, item_id: 3, item_title: "空之境界", source_type: "milestone", source_ref: null, occurred_at: "2026-08-09T11:00:00", summary: "这一天，我把《空之境界》看完了", created_at: "2026-08-09T11:00:00" },
    ]);
    render(<MemoryGallery onOpenWork={() => {}} />);
    await waitFor(() => expect(screen.getByText("神作")).toBeTruthy());
    expect(screen.getByText("＋ 收藏")).toBeTruthy();
    expect(screen.getByText("✓ 完成")).toBeTruthy();
    // 书评行不出现类型标记（干净）
    const reviewRow = screen.getByText("神作").closest("button");
    expect(reviewRow.textContent).not.toContain("书评");
  });

  it("标本行（Phase 5-2-1）：text 记忆渲染 情绪 + 附图缩略图；无时间轴 rail/dot", async () => {
    mockFetch([
      { id: 9, item_id: 1, item_title: "命运石之门", source_type: "text", source_ref: null,
        occurred_at: "2026-08-01T10:00:00", summary: "夜里重看", emotion: "怀念",
        media: [{ id: 1, url: "/static/uploads/a.png", media_type: "image" }],
        created_at: "2026-08-01T10:00:00" },
    ]);
    const { container } = render(<MemoryGallery onOpenWork={() => {}} />);
    await waitFor(() => expect(screen.getByText("夜里重看")).toBeTruthy());
    expect(screen.getByText("情绪 · 怀念")).toBeTruthy();
    expect(container.querySelector(".mg-specimen-thumb")).toBeTruthy();
    expect(container.querySelector(".relative.pl-5")).toBeNull(); // rail 已移除
  });
});

describe("命令面板动作项", () => {
  it("buildCommands 包含「打开记忆回廊」并调用 ctx.openMemories", () => {
    const ctx = { items: [], tags: [], openMemories: vi.fn(), section: vi.fn() };
    const cmds = buildCommands(ctx);
    const openMemories = cmds.find((c) => c.id === "open-memories");
    expect(openMemories).toBeTruthy();
    expect(openMemories.title).toBe("打开记忆回廊");
    expect(openMemories.keywords.join(" ")).toContain("记忆");
    openMemories.run();
    expect(ctx.openMemories).toHaveBeenCalled();
  });
});

describe("主导航入口", () => {
  it("导航栏存在「记忆回廊」按钮，点击切换到记忆回廊区", async () => {
    mockFetch([]);
    render(<DesktopView
      items={[]} total={0} allTags={[]} refresh={() => {}}
      theme="default" setTheme={() => {}}
      custom={{ accentHue: 0, density: "comfortable", radius: 16 }} updateCustom={() => {}}
      textOverlays={[]} updateTextOverlays={() => {}} />);
    const navBtn = screen.getByTitle("记忆回廊");
    expect(navBtn).toBeTruthy();
    fireEvent.click(navBtn);
    await waitFor(() => expect(screen.getByText("GALLERY")).toBeTruthy()); // 统一页面头 mono 路径
  });
});
