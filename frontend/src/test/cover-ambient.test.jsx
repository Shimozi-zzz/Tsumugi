// CoverAmbient（ADR 0037）：卡片/书脊 hover 触发封面取色高光、离开恢复、无封面降级
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import React from "react";
import CoverAmbient from "../components/CoverAmbient.jsx";
import Bookshelf from "../components/Bookshelf.jsx";

vi.mock("../ambient.js", async (importOriginal) => {
  const mod = await importOriginal();
  return { ...mod, extractPalette: vi.fn() };
});
import { extractPalette } from "../ambient.js";

function ok(payload, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(payload) });
}

function glowBox(container) {
  const el = container.querySelector('[data-testid="ambient-hover"]');
  return el ? el.style.boxShadow : "";
}
function glowTransition(container) {
  const el = container.querySelector('[data-testid="ambient-hover"]');
  return el ? el.style.transition : "";
}

beforeEach(() => { localStorage.clear(); extractPalette.mockClear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("CoverAmbient（hover 取色高光）", () => {
  it("hover 触发取色（懒加载），光晕用封面主色", async () => {
    extractPalette.mockImplementation((src) =>
      Promise.resolve(src.includes("red") ? { primary: { r: 210, g: 40, b: 40 }, secondary: null } : null));
    const { container } = render(<CoverAmbient src="https://x/red.jpg"><div>卡片</div></CoverAmbient>);
    expect(extractPalette).not.toHaveBeenCalled(); // 页面加载不预先计算
    fireEvent.mouseEnter(screen.getByText("卡片"));
    await vi.waitFor(() => expect(glowBox(container)).toContain("210,40,40"));
    expect(glowBox(container)).toContain("0 0 18px 2px");
    // 强度弱于详情面板（ambient-alpha × 0.6 ≈ 0.096）
    expect(glowBox(container)).toMatch(/rgba\(210,\s*40,\s*40,\s*0\.0\d+\)/);
  });

  it("离开 hover 恢复透明（平滑过渡）", async () => {
    extractPalette.mockResolvedValue({ primary: { r: 210, g: 40, b: 40 }, secondary: null });
    const { container } = render(<CoverAmbient src="https://x/red.jpg"><div>卡片</div></CoverAmbient>);
    fireEvent.mouseEnter(screen.getByText("卡片"));
    await vi.waitFor(() => expect(glowBox(container)).toContain("210,40,40"));
    expect(glowTransition(container)).toContain("box-shadow 0.3s");
    fireEvent.mouseLeave(screen.getByText("卡片"));
    expect(glowBox(container)).toContain("transparent");
  });

  it("无封面/取色失败 → 回退主题 accent 高亮（仍保留 hover 反馈）", async () => {
    extractPalette.mockResolvedValue(null);
    const { container } = render(<CoverAmbient src="https://x/gray.jpg"><div>卡片</div></CoverAmbient>);
    fireEvent.mouseEnter(screen.getByText("卡片"));
    expect(glowBox(container)).toContain("color-mix(in srgb, var(--accent) 16%, transparent)");
    // 无 src 也一样走 accent 降级
    extractPalette.mockClear();
    cleanup();
    const { container: c2 } = render(<CoverAmbient src={null}><div>无封面</div></CoverAmbient>);
    fireEvent.mouseEnter(screen.getByText("无封面"));
    expect(glowBox(c2)).toContain("var(--accent)");
    expect(extractPalette).not.toHaveBeenCalled();
  });
});

describe("Bookshelf 书脊 hover 高光", () => {
  const ITEMS = [
    { id: 1, title: "红封作品", type: "external_ref", source: "bangumi", tags: [], chunks_count: 1 },
    { id: 2, title: "本地笔记", type: "note", source: "local", tags: [], chunks_count: 1 },
  ];

  function mockFetch() {
    global.fetch = vi.fn((url) => {
      if (String(url).includes("/items/1/detail")) return ok({ id: 1, title: "红封作品", my_rating: 8, image_url: null, file_path: null });
      return ok({});
    });
  }

  it("hover 书脊浮现取色高光，且不覆盖标签分类的书脊主色", async () => {
    mockFetch();
    extractPalette.mockImplementation((src) =>
      Promise.resolve(src && src.includes("red") ? { primary: { r: 210, g: 40, b: 40 }, secondary: null } : null));
    const { container } = render(
      <Bookshelf items={ITEMS} coverOf={(it) => (it.id === 1 ? "https://x/red.jpg" : null)}
        onOpenItem={() => {}} />
    );
    // 书脊主体色 = 标签哈希派生（spineColor），不是取色色
    const spine = [...container.querySelectorAll("button")].find((b) => b.textContent.includes("红封作品"));
    expect(spine.style.backgroundColor).toContain("rgb"); // 标签哈希色
    fireEvent.mouseEnter(spine);
    // 外层 CoverAmbient 光晕层出现取色色
    await vi.waitFor(() => {
      const glow = container.querySelectorAll('[data-testid="ambient-hover"]');
      const active = [...glow].find((g) => g.style.boxShadow.includes("210,40,40"));
      expect(active).toBeTruthy();
    });
  });

  it("书脊无封面时 hover 用 accent 降级高光", async () => {
    mockFetch();
    extractPalette.mockResolvedValue(null);
    const { container } = render(
      <Bookshelf items={ITEMS} coverOf={(it) => null} onOpenItem={() => {}} />
    );
    const spine = [...container.querySelectorAll("button")].find((b) => b.textContent.includes("本地笔记"));
    fireEvent.mouseEnter(spine);
    const glow = [...container.querySelectorAll('[data-testid="ambient-hover"]')].find((g) => g.style.boxShadow.includes("var(--accent)"));
    expect(glow).toBeTruthy();
  });
});
