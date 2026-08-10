// 神殿首页（ADR 0039）：空间隐喻渲染、氛围色环境光、每日一次仪式过渡
// （ADR 0040 / Phase E）：看守猫娘台词按真实数据展示，本次访问内稳定；往年今日命中时
// 展示可点击的"◇ 往年今日"台词并打开只读书评弹层
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import React from "react";
import HomeShrine from "../components/HomeShrine.jsx";
import { MASCOT_LINES, resetMascotSession } from "../mascot.js";

vi.mock("../ambient.js", async (importOriginal) => {
  const mod = await importOriginal();
  return { ...mod, extractPalette: vi.fn() };
});
import { extractPalette } from "../ambient.js";

function ok(payload, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(payload) });
}

// HomeShrine 会异步调 /memories（往年今日，Phase E）与 /items/{id}/reviews（只读弹层）
function mockFetch({ memories = [], reviews = [] } = {}) {
  global.fetch = vi.fn((url) => {
    const u = String(url);
    if (u.includes("/memories")) return ok(memories);
    if (u.includes("/reviews")) return ok(reviews);
    return ok({});
  });
}

function isoHoursAgo(h) {
  return new Date(Date.now() - h * 60 * 60 * 1000).toISOString();
}

function renderShrine(overrides = {}) {
  return render(
    <HomeShrine
      representativeCover={overrides.rep ?? null}
      recentItems={overrides.items ?? []}
      recentReviews={overrides.reviews ?? []}
      onOpenWork={overrides.onOpenWork ?? (() => {})}
      collectionCount={overrides.collectionCount ?? null}
      reviewCount={overrides.reviewCount ?? null}
      newestCollectionAt={overrides.newestCollectionAt ?? null}
      newestReviewAt={overrides.newestReviewAt ?? null}
    >
      <input placeholder="搜索知识库并提问" />
    </HomeShrine>
  );
}

function ambientLayer(container) {
  return [...container.querySelectorAll("div")].find((d) =>
    (d.style.background || "").includes("radial-gradient"));
}

beforeEach(() => { localStorage.clear(); resetMascotSession(); extractPalette.mockClear(); mockFetch(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("HomeShrine（神殿首页）", () => {
  it("渲染鸟居轮廓 + 焦点搜索栏 + 最近供奉（纵深排布）", () => {
    const { container } = renderShrine({
      items: [
        { id: 1, title: "作品甲", source: "bangumi", image_url: "https://x/a.jpg", file_path: null },
        { id: 2, title: "作品乙", source: "bangumi", image_url: "https://x/b.jpg", file_path: null },
      ],
    });
    expect(screen.getByPlaceholderText("搜索知识库并提问")).toBeTruthy(); // 焦点（children 传入的搜索栏）
    expect(container.querySelector("svg")).toBeTruthy(); // 鸟居轮廓线（几何符号）
    expect(screen.getByText("最近供奉")).toBeTruthy();
    expect(screen.getByTitle("作品甲")).toBeTruthy();
    expect(screen.getByTitle("作品乙")).toBeTruthy();
  });

  it("有代表封面 → 取色后出现环境光背景；无封面 → 降级主题表面色（无环境光）", async () => {
    extractPalette.mockResolvedValue({ primary: { r: 210, g: 40, b: 40 }, secondary: null });
    const { container } = renderShrine({ rep: "https://x/red.jpg" });
    await vi.waitFor(() => expect(extractPalette).toHaveBeenCalledWith("https://x/red.jpg"));
    await vi.waitFor(() => expect(ambientLayer(container)?.style.background).toContain("radial-gradient"));
    const ambient = ambientLayer(container);
    expect(ambient.style.background).toContain("210,40,40");
    expect(ambient.style.opacity).toBe("1");

    // 无封面 → 环境光层仍渲染但无渐变（opacity 0，回退主题表面色）
    extractPalette.mockClear();
    cleanup();
    const { container: c2 } = renderShrine({ rep: null });
    expect(ambientLayer(c2)).toBeFalsy();
    expect(extractPalette).not.toHaveBeenCalled();
  });

  it("每日首次打开播放仪式（暗幕），同日再次进入不重复", () => {
    const { container } = renderShrine();
    expect(container.querySelector(".shrine").className).toContain("shrine-ritual");
    expect(container.querySelector(".shrine-veil")).toBeTruthy();
    expect(localStorage.getItem("tsumugi-home-ritual")).toBeTruthy();

    // 同日重新进入（重新挂载）→ 简化版/无仪式
    cleanup();
    const { container: c2 } = renderShrine();
    expect(c2.querySelector(".shrine").className).not.toContain("shrine-ritual");
    expect(c2.querySelector(".shrine").className).toContain("shrine-revealed");
  });

  it("点击可跳过仪式（立即完成揭幕，transition 关闭）", () => {
    const { container } = renderShrine();
    const shrine = container.querySelector(".shrine");
    expect(shrine.className).toContain("shrine-ritual");
    fireEvent.click(document.body);
    expect(shrine.className).toContain("shrine-skip");
    expect(shrine.className).toContain("shrine-revealed");
  });

  it("数据就绪 + 最近有新收藏 → 展示猫娘台词（来自 new_collection 库），本次访问内稳定", async () => {
    vi.spyOn(Math, "random").mockReturnValueOnce(0).mockReturnValue(0.99);
    const { container, rerender } = renderShrine({
      collectionCount: 3,
      reviewCount: 0,
      newestCollectionAt: isoHoursAgo(1),
    });
    await waitFor(() => {
      const lineEl = [...container.querySelectorAll(".shrine-item")].find((d) => MASCOT_LINES.new_collection.includes(d.textContent));
      expect(lineEl).toBeTruthy();
    });
    const lineEl = [...container.querySelectorAll(".shrine-item")].find((d) => MASCOT_LINES.new_collection.includes(d.textContent));
    const firstLine = lineEl.textContent;
    expect(MASCOT_LINES.new_collection[0]).toBe(firstLine); // random=0 → 第一句

    // 同一次访问内（rerender）不换台词（chosenRef 冻结；若重新随机会变成最后一句）
    rerender(
      <HomeShrine
        representativeCover={null}
        recentItems={[]}
        recentReviews={[]}
        collectionCount={3}
        reviewCount={0}
        newestCollectionAt={isoHoursAgo(1)}>
        <input placeholder="搜索知识库并提问" />
      </HomeShrine>
    );
    const lineEl2 = [...container.querySelectorAll(".shrine-item")].find((d) => MASCOT_LINES.new_collection.includes(d.textContent));
    expect(lineEl2.textContent).toBe(firstLine);
  });

  it("收藏数命中里程碑 → 展示对应里程碑台词", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    const { container } = renderShrine({ collectionCount: 100, reviewCount: 0 });
    await waitFor(() => {
      const el = [...container.querySelectorAll(".shrine-item")].find((d) => MASCOT_LINES.milestones["collection:100"].includes(d.textContent));
      expect(el).toBeTruthy();
    });
    const el = [...container.querySelectorAll(".shrine-item")].find((d) => MASCOT_LINES.milestones["collection:100"].includes(d.textContent));
    expect(MASCOT_LINES.milestones["collection:100"][0]).toBe(el.textContent);
  });

  it("往年今日命中 → 展示可点击台词（含年份/标题/摘要），点击打开只读书评弹层", async () => {
    mockFetch({
      memories: [{ id: 99, item_id: 1, item_title: "命运石之门", source_type: "review", source_ref: 10, occurred_at: "2024-08-09T10:00:00", summary: "神作", created_at: "2024-08-09T10:00:00" }],
      reviews: [{ id: 10, item_id: 1, title: "神作", content: "# 标题\n正文", rating: 9, status: "看完", created_at: "2024-08-09T10:00:00" }],
    });
    vi.spyOn(Math, "random").mockReturnValue(0);
    const { container } = renderShrine({ collectionCount: 3, reviewCount: 0 });
    await waitFor(() => expect(screen.getByText("◇ 往年今日")).toBeTruthy());
    const line = [...container.querySelectorAll("button")].find((b) => b.textContent.includes("命运石之门"));
    expect(line).toBeTruthy();
    expect(line.textContent).toContain("《命运石之门》");
    expect(line.textContent).toContain("神作");
    fireEvent.click(line);
    await waitFor(() => expect(document.querySelector(".doc h1")?.textContent).toBe("标题"));
  });

  it("往年今日未命中 → 日常问候照常，不出现往年今日标记", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    renderShrine({ collectionCount: 3, reviewCount: 0, newestCollectionAt: isoHoursAgo(1) });
    await waitFor(() => {
      const anyLine = [...document.querySelectorAll(".shrine-item")].some((d) => MASCOT_LINES.new_collection.includes(d.textContent));
      expect(anyLine).toBeTruthy();
    });
    expect(screen.queryByText("◇ 往年今日")).toBeNull();
  });

  it("数据未就绪（counts 为 null）→ 不展示猫娘台词", () => {
    const { container } = renderShrine({ collectionCount: null, reviewCount: null, newestCollectionAt: isoHoursAgo(1) });
    const lines = [...container.querySelectorAll(".shrine-item")].map((d) => d.textContent);
    const mascotText = Object.values(MASCOT_LINES).flatMap((v) => (Array.isArray(v) ? v : Object.values(v).flat())).filter(Boolean);
    expect(lines.some((t) => mascotText.includes(t))).toBe(false);
  });
});
