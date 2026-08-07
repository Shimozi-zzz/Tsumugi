// 安利卡：短评选取（含 spoiler 过滤）、卡片 SVG 渲染组合、导出下载触发
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import {
  selectQuote, cleanQuote, buildShareCardSvg, wrapText, escapeXml,
} from "../shareCard.js";

const COLORS = {
  bg: "#0b0f19", panel: "#1e2230", accent: "#f09199",
  text: "#f3f4f6", textSec: "#9ca3af", tagBg: "rgba(255,255,255,0.08)", tagText: "#a5d8f7",
};

describe("selectQuote（短评选取 + spoiler 过滤）", () => {
  const mk = (content, spoiler, id = 1) => ({ id, content, spoiler });

  it("取最新一条非 spoiler review", () => {
    const reviews = [
      mk("最新感想：节奏很好", false, 3),
      mk("较早的感想", false, 2),
    ];
    expect(selectQuote(reviews)).toBe("最新感想：节奏很好");
  });

  it("最新一条是 spoiler 时，跳过它选更早的非 spoiler", () => {
    const reviews = [
      mk("剧透内容绝不进卡片", true, 3),
      mk("安全的短评", false, 2),
    ];
    expect(selectQuote(reviews)).toBe("安全的短评");
  });

  it("全部 spoiler → null（调用方显示作者选择不剧透）", () => {
    const reviews = [mk("剧透1", true), mk("剧透2", true)];
    expect(selectQuote(reviews)).toBeNull();
  });

  it("无 review → null", () => {
    expect(selectQuote([])).toBeNull();
    expect(selectQuote(null)).toBeNull();
  });

  it("顺序无关：过滤只看 spoiler 标志 + 数组首位为最新", () => {
    const reviews = [mk("最新但剧透", true), mk("次新安全", false), mk("更早剧透", true)];
    expect(selectQuote(reviews)).toBe("次新安全");
  });
});

describe("cleanQuote（清洗 + 截断）", () => {
  it("折叠空白并截断加省略号", () => {
    const long = "这是一段很长的评语，远远超过六十个字符的限制，需要被截断处理以适配安利卡的短评区域展示，所以继续填充更多文字让它足够长足够长足够长。";
    const q = cleanQuote(long);
    expect(q.endsWith("…")).toBe(true);
    expect(q.length).toBeLessThanOrEqual(61);
  });

  it("空内容 → null", () => {
    expect(cleanQuote(null)).toBeNull();
    expect(cleanQuote("   ")).toBeNull();
    expect(cleanQuote("")).toBeNull();
  });

  it("短内容原样", () => {
    expect(cleanQuote(" 不错的作品  ")).toBe("不错的作品");
  });
});

describe("buildShareCardSvg 组合", () => {
  const base = { title: "辉夜大小姐想让我告白", coverHref: null, rating: null, quote: null, spoilerOnly: false, source: "bangumi", colors: COLORS };

  it("有评分时渲染评分区，无评分时整块省略（不显示暂无）", () => {
    const withRating = buildShareCardSvg({ ...base, rating: 8.0 });
    expect(withRating).toContain("我的评分");
    expect(withRating).toContain("8");
    const without = buildShareCardSvg({ ...base, rating: null });
    expect(without).not.toContain("我的评分");
  });

  it("有短评时渲染引号内容", () => {
    const svg = buildShareCardSvg({ ...base, quote: "节奏紧凑，值得一看" });
    expect(svg).toContain("「节奏紧凑，值得一看」");
  });

  it("全部 spoiler → 显示作者选择不剧透", () => {
    const svg = buildShareCardSvg({ ...base, quote: null, spoilerOnly: true });
    expect(svg).toContain("作者选择不剧透");
  });

  it("无 review 且无短评 → 短评区整块省略", () => {
    const svg = buildShareCardSvg({ ...base, quote: null, spoilerOnly: false });
    expect(svg).not.toContain("作者选择不剧透");
    expect(svg).not.toContain("「");
  });

  it("标题/文本 XML 转义", () => {
    const svg = buildShareCardSvg({ ...base, title: "A & B <C>" });
    expect(svg).toContain("A &amp; B &lt;C&gt;");
    expect(escapeXml("&<>\"'")).toBe("&amp;&lt;&gt;&quot;&apos;");
  });

  it("无封面 → 占位图（不含 image 标签）", () => {
    const svg = buildShareCardSvg({ ...base, coverHref: null });
    expect(svg).not.toContain("<image");
    expect(svg).toContain("thumbGrad");
  });

  it("有封面 → 内联 data URL", () => {
    const svg = buildShareCardSvg({ ...base, coverHref: "data:image/jpeg;base64,AAA" });
    expect(svg).toContain("<image");
    expect(svg).toContain("data:image/jpeg;base64,AAA");
  });
});

describe("wrapText", () => {
  it("按固定字符数断行", () => {
    expect(wrapText("abcdefghij", 4)).toEqual(["abcd", "efgh", "ij"]);
  });
  it("空串", () => {
    expect(wrapText("", 4)).toEqual([]);
  });
});

describe("ShareCardModal（渲染 + 下载）", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("渲染 SVG 预览 + 下载按钮，点击触发导出", async () => {
    const shareCard = await import("../shareCard.js");
    vi.spyOn(shareCard, "downloadSvgAsPng").mockResolvedValue(undefined);
    vi.spyOn(shareCard, "imageUrlToDataUrl").mockResolvedValue(null);

    const Modal = (await import("../components/ShareCardModal.jsx")).default;
    global.fetch = vi.fn((url) => {
      if (String(url).includes("/reviews")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([
          { id: 1, content: "剧透：凶手是管家", spoiler: true },
          { id: 2, content: "非剧透：节奏紧凑", spoiler: false },
        ]) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({
        id: 7, title: "辉夜大小姐", source: "bangumi", my_rating: 8.5,
        file_path: null, image_url: null,
      }) });
    });

    render(<Modal item={{ id: 7 }} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("安利卡预览")).toBeTruthy());
    expect(screen.getByText("下载图片 (PNG)")).toBeTruthy();
    // SVG 已渲染：应含评分 + 非剧透短评，不应含剧透内容
    await waitFor(() => expect(document.querySelector("svg")).toBeTruthy());
    const svgText = document.querySelector("svg").innerHTML;
    expect(svgText).toContain("我的评分");
    expect(svgText).toContain("非剧透：节奏紧凑");
    expect(svgText).not.toContain("凶手是管家");

    fireEvent.click(screen.getByText("下载图片 (PNG)"));
    await waitFor(() => expect(shareCard.downloadSvgAsPng).toHaveBeenCalledTimes(1));
  });

  it("全部 spoiler → 预览显示作者选择不剧透", async () => {
    const shareCard = await import("../shareCard.js");
    vi.spyOn(shareCard, "imageUrlToDataUrl").mockResolvedValue(null);
    const Modal = (await import("../components/ShareCardModal.jsx")).default;
    global.fetch = vi.fn((url) => {
      if (String(url).includes("/reviews")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([
          { id: 1, content: "剧透：凶手是管家", spoiler: true },
        ]) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({
        id: 8, title: "某作品", source: "bangumi", my_rating: null,
        file_path: null, image_url: null,
      }) });
    });
    render(<Modal item={{ id: 8 }} onClose={() => {}} />);
    await waitFor(() => expect(document.querySelector("svg")).toBeTruthy());
    const svgText = document.querySelector("svg").innerHTML;
    expect(svgText).toContain("作者选择不剧透");
    expect(svgText).not.toContain("我的评分"); // 无评分 → 评分区省略
    expect(svgText).not.toContain("凶手是管家");
  });
});
