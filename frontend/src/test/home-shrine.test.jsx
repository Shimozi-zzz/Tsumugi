// 神殿首页（ADR 0039）：空间隐喻渲染、氛围色环境光、每日一次仪式过渡
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import React from "react";
import HomeShrine from "../components/HomeShrine.jsx";

vi.mock("../ambient.js", async (importOriginal) => {
  const mod = await importOriginal();
  return { ...mod, extractPalette: vi.fn() };
});
import { extractPalette } from "../ambient.js";

function renderShrine(overrides = {}) {
  return render(
    <HomeShrine
      representativeCover={overrides.rep ?? null}
      recentItems={overrides.items ?? []}
      recentReviews={overrides.reviews ?? []}
      onOpenWork={overrides.onOpenWork ?? (() => {})}
    >
      <input placeholder="搜索知识库并提问" />
    </HomeShrine>
  );
}

function ambientLayer(container) {
  return [...container.querySelectorAll("div")].find((d) =>
    (d.style.background || "").includes("radial-gradient"));
}

beforeEach(() => { localStorage.clear(); extractPalette.mockClear(); });
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
});
