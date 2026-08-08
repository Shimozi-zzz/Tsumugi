// 封面动态取色氛围（ADR 0034）：取色函数样例/边界降级、详情面板氛围色随条目更新
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, waitFor, cleanup } from "@testing-library/react";
import React from "react";
import { dominantColors, isVivid, rgbToHsl } from "../ambient.js";
import ItemDetailPanel from "../components/ItemDetailPanel.jsx";

vi.mock("../ambient.js", async (importOriginal) => {
  const mod = await importOriginal();
  return { ...mod, extractPalette: vi.fn() };
});
import { extractPalette } from "../ambient.js";

function solidPixels(r, g, b, n = 32 * 32) {
  const px = new Uint8ClampedArray(n * 4);
  for (let i = 0; i < n; i++) { const o = i * 4; px[o] = r; px[o + 1] = g; px[o + 2] = b; px[o + 3] = 255; }
  return px;
}
function transparentBlack(n = 32 * 32) {
  return new Uint8ClampedArray(n * 4); // 全 0 且 alpha=0
}

function ok(payload, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(payload) });
}

beforeEach(() => { localStorage.clear(); extractPalette.mockClear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("dominantColors（取色算法）", () => {
  it("纯红封面 → 主色为红（不同条目真实反映封面主色）", () => {
    const p = dominantColors(solidPixels(220, 40, 40));
    expect(p).toBeTruthy();
    expect(p.primary.r).toBeGreaterThan(180);
    expect(p.primary.g).toBeLessThan(100);
  });

  it("纯蓝封面 → 主色为蓝（色调差异明显）", () => {
    const p = dominantColors(solidPixels(40, 90, 220));
    expect(p.primary.b).toBeGreaterThan(180);
    expect(p.primary.r).toBeLessThan(100);
  });

  it("边界降级：纯白/纯黑/中灰 → null（回退主题表面色）", () => {
    expect(dominantColors(solidPixels(250, 250, 250))).toBeNull();
    expect(dominantColors(solidPixels(10, 10, 10))).toBeNull();
    expect(dominantColors(solidPixels(128, 128, 128))).toBeNull();
  });

  it("透明像素被跳过：全透明 → null", () => {
    expect(dominantColors(transparentBlack())).toBeNull();
  });

  it("红 64% + 绿 36% → 主色红、次色绿（hue 差异足够才保留第二主色）", () => {
    const px = new Uint8ClampedArray(32 * 32 * 4);
    for (let i = 0; i < 32 * 32; i++) {
      const o = i * 4;
      if (i % 100 < 64) { px[o] = 220; px[o + 1] = 40; px[o + 2] = 40; }
      else { px[o] = 40; px[o + 1] = 180; px[o + 2] = 50; }
      px[o + 3] = 255;
    }
    const p = dominantColors(px);
    expect(p.primary.g).toBeLessThan(100);          // 主色红
    expect(p.secondary).toBeTruthy();
    expect(p.secondary.g).toBeGreaterThan(120);      // 次色绿
  });

  it("isVivid / rgbToHsl 边界", () => {
    expect(isVivid(220, 40, 40)).toBe(true);
    expect(isVivid(250, 250, 250)).toBe(false);
    expect(isVivid(10, 10, 10)).toBe(false);
    expect(isVivid(128, 128, 128)).toBe(false);
    expect(rgbToHsl(255, 0, 0).h).toBe(0);
    expect(rgbToHsl(0, 255, 0).h).toBe(120);
  });
});

describe("ItemDetailPanel 氛围色", () => {
  const DETAILS = {
    1: { id: 1, title: "红封面作品", source: "bangumi", description: "d", image_url: "https://x/cover1.jpg",
         rating: null, my_rating: null, tags: [], reference_text: "", social: {}, raw_metadata: null, characters: [], file_path: null },
    2: { id: 2, title: "蓝封面作品", source: "bangumi", description: "d", image_url: "https://x/cover2.jpg",
         rating: null, my_rating: null, tags: [], reference_text: "", social: {}, raw_metadata: null, characters: [], file_path: null },
    3: { id: 3, title: "本地无封面", source: "local", description: "d", image_url: null,
         rating: null, my_rating: null, tags: [], reference_text: "", social: {}, raw_metadata: null, characters: [], file_path: null },
  };

  function mockFetch() {
    global.fetch = vi.fn((url) => {
      const m = String(url).match(/\/items\/(\d+)\/detail$/);
      if (m) return ok(DETAILS[Number(m[1])] || {});
      return ok({});
    });
  }

  it("氛围光晕使用封面提取的主色调（box-shadow 颜色来自取色结果）", async () => {
    mockFetch();
    extractPalette.mockImplementation((src) =>
      Promise.resolve(src.includes("cover1") ? { primary: { r: 220, g: 40, b: 40 }, secondary: null } : { primary: { r: 40, g: 90, b: 220 }, secondary: null }));
    const { container } = render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(container.querySelector('[data-testid="ambient-glow"]')).toBeTruthy());
    await waitFor(() => expect(extractPalette).toHaveBeenCalledWith("https://x/cover1.jpg"));
    const glow = container.querySelector('[data-testid="ambient-glow"]');
    expect(glow.style.boxShadow).toContain("220,40,40");
    // 功能性元素仍是 token 色（不覆盖文字）：标题色 = var(--text)
    expect(container.querySelector("h2").style.color).toBe("var(--text)");
  });

  it("切换条目 → 氛围色平滑更新为新封面主色（不硬切）", async () => {
    mockFetch();
    extractPalette.mockImplementation((src) =>
      Promise.resolve(src.includes("cover1") ? { primary: { r: 220, g: 40, b: 40 }, secondary: null } : { primary: { r: 40, g: 90, b: 220 }, secondary: null }));
    const { container, rerender } = render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(container.querySelector('[data-testid="ambient-glow"]').style.boxShadow).toContain("220,40,40"));
    rerender(<ItemDetailPanel itemId={2} />);
    await waitFor(() => expect(container.querySelector('[data-testid="ambient-glow"]').style.boxShadow).toContain("40,90,220"));
    // 有 transition（平滑过渡）
    expect(container.querySelector('[data-testid="ambient-glow"]').style.transition).toContain("box-shadow 0.5s");
  });

  it("无封面/本地笔记 → 无氛围色（回退透明，不强行渲染）", async () => {
    mockFetch();
    const { container } = render(<ItemDetailPanel itemId={3} />);
    await waitFor(() => expect(container.querySelector("h2")).toBeTruthy());
    await waitFor(() => {
      const glow = container.querySelector('[data-testid="ambient-glow"]');
      expect(glow.style.boxShadow).toContain("transparent");
    });
    expect(extractPalette).not.toHaveBeenCalled();
  });
});
