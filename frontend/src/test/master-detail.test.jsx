// 主从视图 + 状态分组列表 + Playnite 式信息设计 + 深色主题（ADR 0029）
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import React from "react";
import DesktopView from "../components/DesktopView.jsx";
import StatusGroupedList from "../components/StatusGroupedList.jsx";
import { InfoTable, TagCapsule, itemInfoRows } from "../components/ui.jsx";
import { applyTheme, THEMES } from "../themes.js";

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
    fireEvent.click(screen.getByTitle("图书馆"));
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
    // 基本信息属性表格 + 标签胶囊
    expect(screen.getByText("基本信息")).toBeTruthy();
    expect(screen.getByText("STEINS;GATE")).toBeTruthy(); // InfoTable 值（原名）
    expect(screen.getByText("2011-04")).toBeTruthy();      // InfoTable 值（日期）
    expect(screen.getByText("科幻")).toBeTruthy();          // TagCapsule
  });

  it("切换条目，右侧详情随之切换", async () => {
    mockFetch();
    render(<DesktopView {...PROPS} />);
    fireEvent.click(screen.getByTitle("图书馆"));
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

  it("itemInfoRows：从 raw_metadata 提炼基本信息行", () => {
    const detail = {
      source: "bangumi", rating: 8.9,
      raw_metadata: { detail: { metadata: { original_name: "STEINS;GATE", date: "2011-04" } } },
    };
    const labels = itemInfoRows(detail).map((r) => r.label);
    expect(labels).toEqual(["数据源", "原名", "日期", "大众评分"]);
  });

  it("TagCapsule：统一圆角胶囊（token 颜色）", () => {
    const { container } = render(<TagCapsule text="科幻" />);
    const el = container.querySelector("span");
    expect(el.textContent).toBe("科幻");
    expect(el.className).toContain("rounded-full");
    expect(el.style.backgroundColor).toBe("var(--tag-bg)");
    expect(el.style.color).toBe("var(--tag-text)");
  });
});

describe("深色主题（第4套，token 兼容）", () => {
  it("THEMES 含深色主题", () => {
    expect(THEMES.some((t) => t.key === "dark")).toBe(true);
  });

  it("applyTheme('dark')：data-theme + 深色强调派生（soft 深色染、accent 中亮）", () => {
    applyTheme("dark");
    const el = document.documentElement;
    expect(el.getAttribute("data-theme")).toBe("dark");
    const soft = el.style.getPropertyValue("--accent-soft");
    const accent = el.style.getPropertyValue("--accent");
    expect(soft).toContain("hsl(");
    expect(accent).toContain("hsl(");
    // 深色主题下：soft 明度低（深色染，不是近白），accent 明度中高（深底对比）
    expect(parseHslLightness(soft)).toBeLessThan(20);
    expect(parseHslLightness(accent)).toBeGreaterThan(50);
  });

  it("与浅色主题对比：soft 派生逻辑不同，但都走同一套 token 结构", () => {
    applyTheme("dark");
    const darkSoft = parseHslLightness(document.documentElement.style.getPropertyValue("--accent-soft"));
    applyTheme("default");
    const el = document.documentElement;
    expect(el.getAttribute("data-theme")).toBe("default");
    const lightSoft = parseHslLightness(el.style.getPropertyValue("--accent-soft"));
    expect(lightSoft).toBeGreaterThan(90);
    expect(darkSoft).toBeLessThan(lightSoft);
  });
});

function parseHslLightness(css) {
  const m = /hsl\(([^)]+)\)/.exec(css);
  if (!m) return null;
  const parts = m[1].split(",");
  return parseFloat(parts[2]);
}
