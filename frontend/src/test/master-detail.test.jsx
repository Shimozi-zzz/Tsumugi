// 主从视图 + 状态分组列表 + Playnite 式信息设计 + 深色主题（ADR 0029）
// + ADR 0030 视觉缺陷修复（来源标签完整显示 / 选中背景 / 表面层级 token）
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import React from "react";
import DesktopView from "../components/DesktopView.jsx";
import StatusGroupedList from "../components/StatusGroupedList.jsx";
import { InfoTable, TagCapsule, itemInfoRows, ArchiveNo } from "../components/ui.jsx";

function ok(payload, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(payload) });
}

const ITEMS = [
  { id: 1, title: "命运石之门", type: "external_ref", source: "bangumi", tags: [], content: "", image_url: null, file_path: null, chunks_count: 1 },
  { id: 2, title: "魔法少女小圆", type: "external_ref", source: "moegirl", tags: [], content: "", image_url: null, file_path: null, chunks_count: 1 },
  { id: 3, title: "我的笔记", type: "note", source: "local", tags: [], content: "内容", image_url: null, file_path: null, chunks_count: 1 },
];
const REVIEWS = [
  { id: 10, item_id: 1, item_title: "命运石之门", status: "看完", rating: 9, spoiler: false, font_size: null, title: "神作", content: "x", created_at: "2026-08-01T10:00:00", public_rating: null },
  { id: 11, item_id: 2, item_title: "魔法少女小圆", status: "在看", rating: 8, spoiler: false, font_size: null, title: "", content: "y", created_at: "2026-08-02T10:00:00", public_rating: null },
];
const DETAILS = {
  1: { id: 1, title: "命运石之门", source: "bangumi", description: "简介1", rating: 8.9, my_rating: 9, tags: ["科幻", "时间旅行"], reference_text: "", social: {}, raw_metadata: { detail: { metadata: { original_name: "STEINS;GATE", date: "2011-04" } } }, characters: [], image_url: null, file_path: null },
  2: { id: 2, title: "魔法少女小圆", source: "moegirl", description: "简介2", rating: null, my_rating: 8, tags: ["魔法"], reference_text: "", social: {}, raw_metadata: null, characters: [], image_url: null, file_path: null },
};

function mockFetch() {
  global.fetch = vi.fn((url, opts = {}) => {
    const u = String(url);
    const m = opts.method || "GET";
    const dm = u.match(/\/items\/(\d+)\/detail$/);
    if (dm) return ok(DETAILS[Number(dm[1])] || {});
    if (u.includes("/reviews") && m === "GET") return ok(REVIEWS);
    if (u.includes("/collections") && m === "GET") return ok([{ item_id: 1, status: "看完" }, { item_id: 2, status: "在看" }]);
    if (u.includes("/items") && m === "GET") return ok({ total: ITEMS.length, items: ITEMS });
    if (u.includes("/tags")) return ok([]);
    if (u.includes("/connectors")) return ok([]);
    if (u.includes("/plugins")) return ok({ plugins: [], failures: [], notice_needed: false, plugin_dir: "./plugins" });
    return ok({});
  });
}

const PROPS = {
  items: [], total: 0, allTags: [], refresh: () => {},
  theme: "default", setTheme: () => {},
  custom: { accentHue: 0, density: "comfortable", radius: 16 }, updateCustom: () => {},
  textOverlays: [], updateTextOverlays: () => {},
};

beforeEach(() => { localStorage.clear(); document.documentElement.removeAttribute("data-theme"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("主从视图（Master-Detail）", () => {
  it("列表模式：点击左侧条目，右侧详情立即更新（属性表格/标签胶囊出现）", async () => {
    mockFetch();
    render(<DesktopView {...PROPS} />);
    fireEvent.click(screen.getByTitle("书库"));
    await waitFor(() => screen.getByTitle("分组列表（主从视图）"));
    fireEvent.click(screen.getByTitle("分组列表（主从视图）"));
    // 左侧状态分组出现
    await waitFor(() => expect(screen.getByText("看完")).toBeTruthy());
    // 右侧初始为占位
    expect(screen.getByText(/从左侧列表选择一条资料/)).toBeTruthy();
    // 点击条目 → 详情立即更新
    fireEvent.click(screen.getByText("命运石之门"));
    await waitFor(() => {
      const h2 = document.querySelector("h2");
      expect(h2 && h2.textContent).toBe("命运石之门");
    });
    // 这个世界章节 + 编目（原名/日期）+ 标签胶囊
    expect(screen.getByText("这个世界")).toBeTruthy();
    expect(screen.getByText("STEINS;GATE")).toBeTruthy(); // 编目值（原名）
    expect(screen.getByText("2011-04")).toBeTruthy();      // 编目值（日期）
    expect(screen.getByText("科幻")).toBeTruthy();          // TagCapsule
  });

  it("切换条目，右侧详情随之切换", async () => {
    mockFetch();
    render(<DesktopView {...PROPS} />);
    fireEvent.click(screen.getByTitle("书库"));
    await waitFor(() => screen.getByTitle("分组列表（主从视图）"));
    fireEvent.click(screen.getByTitle("分组列表（主从视图）"));
    await waitFor(() => screen.getByText("在看"));
    fireEvent.click(screen.getByText("魔法少女小圆"));
    await waitFor(() => {
      const h2 = document.querySelector("h2");
      expect(h2 && h2.textContent).toBe("魔法少女小圆");
    });
    expect(screen.getByText("魔法")).toBeTruthy();
  });
});

describe("状态分组列表", () => {
  it("分组标题 + 数量角标 + 折叠展开", () => {
    const items = ITEMS;
    const statusOf = { 1: "看完", 2: "在看" };
    render(<StatusGroupedList items={items} statusOf={statusOf} selectedId={null} onSelect={() => {}} />);
    expect(screen.getByText("看完")).toBeTruthy();
    expect(screen.getByText("在看")).toBeTruthy();
    expect(screen.getByText("未收藏")).toBeTruthy();
    expect(screen.getByText("我的笔记")).toBeTruthy(); // 未收藏组
    // 折叠"看完"组 → 该组条目隐藏
    fireEvent.click(screen.getByText("看完"));
    expect(screen.queryByText("命运石之门")).toBeNull();
    // 其它组不受影响
    expect(screen.getByText("魔法少女小圆")).toBeTruthy();
    // 再次展开
    fireEvent.click(screen.getByText("看完"));
    expect(screen.getByText("命运石之门")).toBeTruthy();
  });

  it("点击条目触发 onSelect", () => {
    const onSelect = vi.fn();
    render(<StatusGroupedList items={ITEMS} statusOf={{}} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByText("我的笔记"));
    expect(onSelect).toHaveBeenCalledWith(3);
  });
});

describe("Playnite 式信息设计（ui 组件）", () => {
  it("InfoTable：label 右对齐 / value 左对齐 / 行间分隔线", () => {
    const { container } = render(
      <InfoTable rows={[{ label: "原名", value: "STEINS;GATE" }, { label: "日期", value: "2011-04" }]} />
    );
    const tds = container.querySelectorAll("td");
    expect(tds.length).toBe(4);
    expect(tds[0].textContent).toBe("原名");
    expect(tds[0].style.textAlign).toBe("right");   // label 右对齐
    expect(tds[1].style.textAlign).toBe("left");    // value 左对齐
    expect(tds[1].textContent).toBe("STEINS;GATE");
    const trs = container.querySelectorAll("tr");
    expect(trs[1].style.borderTop).toContain("1px solid"); // 行间细分隔线
    expect(trs[0].style.borderTop).toBeFalsy();            // 首行无分隔线
  });

  it("itemInfoRows：从 raw_metadata 提炼基本信息行（日期统一为发行日期）", () => {
    const detail = {
      source: "bangumi", rating: 8.9,
      raw_metadata: { detail: { metadata: { original_name: "STEINS;GATE", date: "2011-04" } } },
    };
    const labels = itemInfoRows(detail).map((r) => r.label);
    expect(labels).toEqual(["数据源", "原名", "发行日期", "大众评分"]);
  });

  it("TagCapsule：统一圆角胶囊（token 颜色）", () => {
    const { container } = render(<TagCapsule text="科幻" />);
    const el = container.querySelector("span");
    expect(el.textContent).toBe("科幻");
    expect(el.className).toContain("rounded-full");
    expect(el.style.backgroundColor).toBe("var(--tag-bg)");
    expect(el.style.color).toBe("var(--tag-text)");
  });

  it("ArchiveNo 档案编号：§ 标记 + 数字，颜色走 accent", () => {
    const { container } = render(<ArchiveNo>01</ArchiveNo>);
    const el = container.querySelector('[data-testid="archive-no"]');
    expect(el).toBeTruthy();
    expect(el.textContent).toContain("§");
    expect(el.textContent).toContain("01");
    expect(el.style.color).toBe("var(--accent)");
    const lg = render(<ArchiveNo size="lg">2026</ArchiveNo>);
    expect(lg.container.querySelector('[data-testid="archive-no"]').className).toContain("archive-no-lg");
  });
});

describe("ADR 0030 视觉缺陷修复", () => {
  it("来源标签完整渲染：不截断、与标题有间距（徽标 nowrap + 行 gap + 标题 truncate 隔离）", () => {
    const items = [{ id: 1, title: "钢之炼金术师", type: "external_ref", source: "bangumi", tags: [], chunks_count: null }];
    const { container } = render(<StatusGroupedList items={items} statusOf={{}} selectedId={null} onSelect={() => {}} />);
    const row = container.querySelector("section li button");
    expect(row).toBeTruthy();
    // 徽标文字完整 = "Bangumi"（不是截断的 "bangum"）
    const badge = row.querySelector("span.rounded-full");
    expect(badge).toBeTruthy();
    expect(badge.textContent).toBe("Bangumi");
    expect(badge.className).toContain("whitespace-nowrap"); // 胶囊本身不换行
    // 胶囊外层包一层 shrink-0 + nowrap，确保不被父容器裁切
    expect(badge.parentElement.className).toContain("shrink-0");
    expect(badge.parentElement.className).toContain("whitespace-nowrap");
    // 行内徽标与标题之间 gap（Tailwind gap-2 = 8px）
    expect(row.className).toContain("gap-2");
    // 截断只发生在标题（flex-1 min-w-0 truncate），徽标不在固定宽度容器里
    const title = row.querySelector(".truncate");
    expect(title.textContent).toBe("钢之炼金术师");
    expect(title.className).toContain("min-w-0");
  });

  it("选中行带 rs-list-row-active（accent 低透明度背景 + 强调边框，非仅描边）", () => {
    const items = [
      { id: 1, title: "作品甲", type: "external_ref", source: "bangumi", tags: [], chunks_count: null },
      { id: 2, title: "作品乙", type: "note", source: "local", tags: [], chunks_count: 1 },
    ];
    const { container } = render(<StatusGroupedList items={items} statusOf={{}} selectedId={1} onSelect={() => {}} />);
    const rows = [...container.querySelectorAll("section li button")];
    const activeRow = rows.find((b) => b.textContent.includes("作品甲"));
    const normalRow = rows.find((b) => b.textContent.includes("作品乙"));
    expect(activeRow.className).toContain("rs-list-row-active");
    expect(normalRow.className).toContain("rs-list-row");
    expect(normalRow.className).not.toContain("rs-list-row-active");
  });

  it("表面层级 token 存在（--surface-0/1/2 纸感分层；行 hover/选中 CSS 已定义）", () => {
    const css = fs.readFileSync(path.resolve(__dirname, "../index.css"), "utf8");
    // 默认主题 :root 定义了三档纸感表面色（层级分明）
    const root = css.slice(0, css.indexOf("html[data-theme"));
    expect(root).toContain("--surface-0:");
    expect(root).toContain("--surface-1:");
    expect(root).toContain("--surface-2:");
    // 列表行 hover（surface-2）与选中（accent 低透明度填充）规则存在
    expect(css).toContain(".rs-list-row:hover");
    expect(css).toContain(".rs-list-row-active");
    expect(css).toContain("color-mix(in srgb, var(--accent) 18%, transparent)");
  });
});
