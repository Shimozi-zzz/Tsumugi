// 书架视图：配色分配、渲染、点击进详情、hover 预览评分、视图切换持久化、筛选联动
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import React from "react";
import { stringHash, spineSeed, spineColor, hexToHsl, primaryTag, spineThickness, groupBookshelf } from "../bookshelf.js";
import Bookshelf, { spineColorVaried } from "../components/Bookshelf.jsx";
import DesktopView from "../components/DesktopView.jsx";

const ITEM_A = { id: 1, title: "辉夜大小姐", type: "external_ref", source: "bangumi", tags: ["恋爱"], content: "", image_url: null, file_path: null };
const ITEM_B = { id: 2, title: "命运石之门", type: "external_ref", source: "bangumi", tags: ["科幻"], content: "", image_url: null, file_path: null };

function ok(payload) {
  return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
}

describe("bookshelf 纯函数", () => {
  it("stringHash 稳定且区分不同输入", () => {
    expect(stringHash("恋爱")).toBe(stringHash("恋爱"));
    expect(stringHash("恋爱")).not.toBe(stringHash("科幻"));
  });

  it("spineSeed：同标签同种子，无标签用 id 兜底", () => {
    expect(spineSeed({ id: 1, tags: ["恋爱"] })).toBe(spineSeed({ id: 9, tags: ["恋爱"] }));
    expect(spineSeed({ id: 1, tags: ["恋爱"] })).not.toBe(spineSeed({ id: 1, tags: ["科幻"] }));
    expect(spineSeed({ id: 5, tags: [] })).toBe(spineSeed({ id: 5, tags: undefined }));
  });

  it("primaryTag 取第一个标签", () => {
    expect(primaryTag({ tags: ["a", "b"] })).toBe("a");
    expect(primaryTag({ tags: [] })).toBe("");
  });

  it("hexToHsl 已知值", () => {
    const hsl = hexToHsl("#ff0000");
    expect(Math.round(hsl.h)).toBe(0);
    const invalid = hexToHsl("not-a-color");
    expect(invalid.h).toBe(220); // 回退
  });

  it("spineColor：同 seed 同色、不同 seed 不同色、输出 hsl", () => {
    const accent = "#ec4899";
    const c1 = spineColor(accent, 1);
    const c2 = spineColor(accent, 2);
    expect(c1).toBe(spineColor(accent, 1));
    expect(c1).not.toBe(c2);
    expect(c1).toMatch(/^hsl\(/);
  });

  it("spineColor（ADR 0058 暖粉彩）：饱和度 30-40%、明度 55-65%", () => {
    const accent = "#b25b36";
    for (let seed = 0; seed < 30; seed++) {
      const m = /hsl\(([^)]+)\)/.exec(spineColor(accent, seed));
      const [h, s, l] = m[1].split(",").map((x) => parseFloat(x));
      expect(s).toBeGreaterThanOrEqual(30);
      expect(s).toBeLessThanOrEqual(40);
      expect(l).toBeGreaterThanOrEqual(55);
      expect(l).toBeLessThanOrEqual(65);
      expect(h).toBeGreaterThanOrEqual(0);
      expect(h).toBeLessThan(360);
    }
  });

  it("spineThickness（P5）：正文越长书脊越厚，带钳制；无正文用 chunk 兜底", () => {
    expect(spineThickness({ content: "" })).toBeGreaterThanOrEqual(9);
    const thin = spineThickness({ content: "短" });
    const thick = spineThickness({ content: "长".repeat(10000) });
    expect(thick).toBeGreaterThan(thin);
    expect(thick).toBeLessThanOrEqual(28);
    expect(spineThickness({ content: "长".repeat(100000) })).toBeLessThanOrEqual(28); // 上界钳制
    expect(spineThickness({ content: "", chunks_count: 20 })).toBeGreaterThan(spineThickness({ content: "", chunks_count: 1 }));
  });

  it("groupBookshelf（P5）：按主标签分架，未分类排最后，数量降序", () => {
    const items = [
      { id: 1, title: "A", tags: ["恋爱"] },
      { id: 2, title: "B", tags: ["恋爱"] },
      { id: 3, title: "C", tags: ["科幻"] },
      { id: 4, title: "D", tags: [] },
    ];
    const groups = groupBookshelf(items);
    expect(groups.map((g) => g.tag)).toEqual(["恋爱", "科幻", "未分类"]);
    expect(groups[0].items.map((i) => i.id)).toEqual([1, 2]);
    expect(groups[2].items[0].id).toBe(4);
  });
});

describe("Bookshelf 组件", () => {
  function renderShelf(items = [ITEM_A, ITEM_B], onOpenItem = vi.fn()) {
    return render(<Bookshelf items={items} coverOf={() => null} onOpenItem={onOpenItem} />);
  }

  it("渲染每个条目的书脊 + 竖排标题", () => {
    const { container } = renderShelf();
    expect(screen.getByTitle("辉夜大小姐")).toBeTruthy();
    expect(screen.getByTitle("命运石之门")).toBeTruthy();
    // 书脊标题用 vertical-rl 书写模式
    const vertical = container.querySelector('span[style*="vertical-rl"], span[style*="vertical-rl"]');
    expect(vertical).toBeTruthy();
  });

  it("P5 真书架：按主标签分架 + 层板线 + 取书浮起类", () => {
    const { container } = renderShelf([
      { id: 1, title: "辉夜大小姐", tags: ["恋爱"], content: "" },
      { id: 2, title: "命运石之门", tags: ["科幻"], content: "" },
    ]);
    // 两层书架（恋爱/科幻），每层左侧有目录卡标签
    const groups = [...container.querySelectorAll('[data-testid="shelf-group"]')];
    expect(groups.length).toBe(2);
    const labels = [...container.querySelectorAll('[data-testid="shelf-label"]')].map((l) => l.textContent);
    expect(labels[0]).toContain("恋爱");
    expect(labels[1]).toContain("科幻");
    // 层板线存在
    expect(container.querySelector(".shelf-board")).toBeTruthy();
    // 书脊带取书浮起类
    const book = container.querySelector("button.shelf-book");
    expect(book).toBeTruthy();
    expect(book.className).toContain("shelf-book");
  });

  it("抽书预览含书评摘录（ADR 0058）", async () => {
    global.fetch = vi.fn((url) => {
      const u = String(url);
      if (u.includes("/detail")) return ok({ id: 1, my_rating: 8.5, title: "辉夜大小姐", source: "bangumi" });
      if (u.includes("/reviews")) return ok([{ id: 10, content: "这是一段关于辉夜大小姐的感想，写得很长很长。", spoiler: false }]);
      return ok({});
    });
    renderShelf();
    fireEvent.mouseEnter(screen.getByTitle("辉夜大小姐"));
    await waitFor(() => expect(screen.getByText(/这是一段关于辉夜大小姐/)).toBeTruthy());
  });

  it("点击书脊 → onOpenItem 携带该条目", () => {
    const onOpenItem = vi.fn();
    renderShelf([ITEM_A], onOpenItem);
    fireEvent.click(screen.getByTitle("辉夜大小姐"));
    expect(onOpenItem).toHaveBeenCalledWith(ITEM_A);
  });

  it("空列表显示空书架", () => {
    renderShelf([]);
    expect(screen.getByText("书架是空的")).toBeTruthy();
  });

  it("只渲染传入的（已筛选）条目子集", () => {
    renderShelf([ITEM_B]);
    expect(screen.queryByTitle("辉夜大小姐")).toBeNull();
    expect(screen.getByTitle("命运石之门")).toBeTruthy();
  });

  it("hover 书脊 → 拉取详情并显示我的评分", async () => {
    global.fetch = vi.fn((url) => {
      if (String(url).includes("/detail")) return ok({ id: 1, my_rating: 8.5, title: "辉夜大小姐", source: "bangumi" });
      return ok({});
    });
    renderShelf();
    fireEvent.mouseEnter(screen.getByTitle("辉夜大小姐"));
    await waitFor(() => expect(screen.getByText("我的评分 ★8.5")).toBeTruthy());
  });

  it("hover 时 my_rating 为 null → 预览不显示评分", async () => {
    global.fetch = vi.fn((url) => {
      if (String(url).includes("/detail")) return ok({ id: 1, my_rating: null, title: "辉夜大小姐", source: "bangumi" });
      return ok({});
    });
    renderShelf([ITEM_A]);
    fireEvent.mouseEnter(screen.getByTitle("辉夜大小姐"));
    await waitFor(() => expect(screen.getByTestId("shelf-preview")).toBeTruthy());
    expect(screen.queryByText(/★/)).toBeNull();
  });

  it("抽书预览显示编目号（ADR 0056）", async () => {
    global.fetch = vi.fn((url) => ok({ id: 1, my_rating: null, title: "辉夜大小姐", source: "bangumi" }));
    renderShelf([ITEM_A]);
    fireEvent.mouseEnter(screen.getByTitle("辉夜大小姐"));
    await waitFor(() => expect(screen.getByTestId("shelf-preview")).toBeTruthy());
    expect(screen.getByText("NO. 0001")).toBeTruthy();
  });
});

describe("视图切换 + 持久化 + 筛选联动（DesktopView）", () => {
  const props = {
    items: [], total: 0, allTags: [], refresh: () => {},
    theme: "default", setTheme: () => {},
    custom: { accentHue: 0, density: "comfortable", radius: 16 }, updateCustom: () => {},
    textOverlays: [], updateTextOverlays: () => {},
  };

  function mockFetch() {
    global.fetch = vi.fn((url) => {
      const u = String(url);
      if (u.includes("/tags")) return ok([{ id: 1, name: "恋爱", count: 1 }]);
      if (u.includes("/connectors")) return ok([]);
      if (u.includes("/items")) return ok({ total: 2, items: [ITEM_A, ITEM_B] });
      return ok({});
    });
  }

  beforeEach(() => {
    localStorage.clear();
  });

  it("默认网格，切书架后写入 localStorage 并渲染书脊", async () => {
    mockFetch();
    const { unmount } = render(<DesktopView {...props} />);
    fireEvent.click(screen.getByTitle("书库"));
    await waitFor(() => expect(screen.getByTitle("书架视图")).toBeTruthy());
    fireEvent.click(screen.getByTitle("书架视图"));
    expect(localStorage.getItem("tsumugi-lib-view")).toBe("shelf");
    // 书脊出现
    await waitFor(() => expect(screen.getByTitle("辉夜大小姐")).toBeTruthy());
    unmount();
  });

  it("重挂载后从 localStorage 恢复书架视图", async () => {
    mockFetch();
    const first = render(<DesktopView {...props} />);
    fireEvent.click(screen.getByTitle("书库"));
    await waitFor(() => screen.getByTitle("书架视图"));
    fireEvent.click(screen.getByTitle("书架视图"));
    first.unmount();

    render(<DesktopView {...props} />);
    fireEvent.click(screen.getByTitle("书库"));
    await waitFor(() => expect(screen.getByTitle("辉夜大小姐")).toBeTruthy()); // 书脊直接渲染
  });

  it("书架视图下本地查找筛选仍生效", async () => {
    mockFetch();
    render(<DesktopView {...props} />);
    fireEvent.click(screen.getByTitle("书库"));
    await waitFor(() => screen.getByTitle("书架视图"));
    fireEvent.click(screen.getByTitle("书架视图"));
    await waitFor(() => expect(screen.getByTitle("辉夜大小姐")).toBeTruthy());
    // 输入筛选：只匹配"命运石之门"
    fireEvent.change(screen.getByPlaceholderText("查找存储的内容…"), { target: { value: "命运石之门" } });
    await waitFor(() => expect(screen.getByTitle("命运石之门")).toBeTruthy());
    expect(screen.queryByTitle("辉夜大小姐")).toBeNull();
  });
});

describe("Bookshelf-2：视觉合架 + 色彩节奏（P1/P2）", () => {
  function renderShelf(items) {
    return render(<Bookshelf items={items} coverOf={() => null} onOpenItem={() => {}} />);
  }

  it("小分类（≤2 册）视觉合并进共享架：书不丢失、仍是独立 button、只有一个匣/层板", () => {
    const { container } = renderShelf([
      { id: 1, title: "A", tags: ["恋爱"], content: "" },
      { id: 2, title: "B", tags: ["科幻"], content: "" },
    ]);
    // 两本都在
    expect(container.querySelectorAll("button.shelf-book").length).toBe(2);
    // 共享架容器存在；只生成一个 shelf-case / 一条层板（而非两个全宽空架）
    expect(container.querySelector('[data-testid="shelf-shared"]')).toBeTruthy();
    expect(container.querySelectorAll(".shelf-case").length).toBe(1);
    expect(container.querySelectorAll(".shelf-board").length).toBe(1);
    // 每本书仍是独立 button；两个小组都保留索引（data-testid 语义）
    expect(container.querySelectorAll('[data-testid="shelf-group"]').length).toBe(2);
    const labels = [...container.querySelectorAll('[data-testid="shelf-label"]')].map((l) => l.textContent);
    expect(labels[0]).toContain("恋爱");
    expect(labels[1]).toContain("科幻");
  });

  it("大分类（>2 册）仍为独立 shelf-unit，不产生共享架", () => {
    const big = Array.from({ length: 6 }, (_, i) => ({ id: i + 1, title: "T" + i, tags: ["TV"], content: "x".repeat(2000) }));
    const { container } = renderShelf(big);
    expect(container.querySelector('[data-testid="shelf-shared"]')).toBeNull();
    expect(container.querySelectorAll(".shelf-case").length).toBe(1);
    expect(container.querySelectorAll("button.shelf-book").length).toBe(6);
  });

  it("混合：大分类独立单元 + 小分类共享架，书总数不变", () => {
    const items = [
      ...Array.from({ length: 6 }, (_, i) => ({ id: 100 + i, title: "T" + i, tags: ["TV"], content: "x".repeat(2000) })),
      { id: 200, title: "S1", tags: ["百合"], content: "" },
      { id: 201, title: "S2", tags: ["神作"], content: "" },
    ];
    const { container } = renderShelf(items);
    expect(container.querySelectorAll("button.shelf-book").length).toBe(8);
    expect(container.querySelectorAll('[data-testid="shelf-group"]').length).toBe(3); // TV + 百合 + 神作
    expect(container.querySelectorAll(".shelf-case").length).toBe(2); // TV 匣 + 共享匣
    expect(container.querySelectorAll(".shelf-board").length).toBe(2);
  });

  it("selectMode：每本书显示小型选择标记，aria-pressed 正确", () => {
    const sel = new Set([1]);
    const { container } = render(
      <Bookshelf items={[ITEM_A, ITEM_B]} coverOf={() => null} onOpenItem={() => {}}
        selectMode selectedIds={sel} />,
    );
    expect(container.querySelectorAll(".shelf-book-mark").length).toBe(2);
    expect(screen.getByTitle("辉夜大小姐").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTitle("命运石之门").getAttribute("aria-pressed")).toBeNull();
  });

  it("context menu：onContextMenu 回调被触发", () => {
    const onCtx = vi.fn();
    render(<Bookshelf items={[ITEM_A]} coverOf={() => null} onOpenItem={() => {}} onContextMenu={onCtx} />);
    fireEvent.contextMenu(screen.getByTitle("辉夜大小姐"));
    expect(onCtx).toHaveBeenCalledTimes(1);
  });

  it("P2 色彩节奏：同类书颜色 deterministic、±12° 内、且同架存在差异（非整架同色）", () => {
    const accent = "#f09199";
    const base = spineColor(accent, spineSeed({ id: 1, tags: ["恋爱"] }));
    const hueOf = (s) => parseFloat(/hsl\(\s*([\d.]+)/.exec(s)[1]);
    const adist = (a, b) => { const d = Math.abs(a - b) % 360; return Math.min(d, 360 - d); };
    // 10 本同类书：色相差异 ≤ 12°，且颜色不全相同（自然藏书节奏）
    const ids = Array.from({ length: 10 }, (_, i) => i + 1);
    const colors = ids.map((id) => spineColorVaried(accent, { id, tags: ["恋爱"] }));
    for (const c of colors) expect(adist(hueOf(c), hueOf(base))).toBeLessThanOrEqual(12);
    expect(new Set(colors).size).toBeGreaterThan(1);
    // deterministic：同 id 恒同色
    expect(spineColorVaried(accent, { id: 5, tags: ["恋爱"] }))
      .toBe(spineColorVaried(accent, { id: 5, tags: ["恋爱"] }));
  });
});
