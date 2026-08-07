// 手写 Markdown 渲染器 + 沉浸式书评工作室（左参考区 + 右编辑器/预览/字号/工具栏）
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import React from "react";
import { renderMarkdown } from "../markdown.js";
import ReviewStudio from "../components/ReviewStudio.jsx";

describe("renderMarkdown", () => {
  it("标题/加粗/斜体/删除线", () => {
    const html = renderMarkdown("## 感想\n\n这是**重点**和*斜体*，~~划掉~~");
    expect(html).toContain("<h2>感想</h2>");
    expect(html).toContain("<strong>重点</strong>");
    expect(html).toContain("<em>斜体</em>");
    expect(html).toContain("<del>划掉</del>");
  });

  it("列表与引用", () => {
    const html = renderMarkdown("- 第一\n- 第二\n\n> 引用一段");
    expect(html).toContain("<ul>");
    expect(html).toContain("<li>第一</li>");
    expect(html).toContain("<blockquote>引用一段</blockquote>");
  });

  it("fenced 代码块", () => {
    const html = renderMarkdown("```python\nprint(1)\n```");
    expect(html).toContain("<pre><code>");
  });

  it("链接仅允许 http(s)", () => {
    const html = renderMarkdown("[点我](https://vndb.org)");
    expect(html).toContain('href="https://vndb.org"');
  });

  it("HTML 转义防 XSS", () => {
    const html = renderMarkdown("<script>alert(1)</script>");
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script");
  });
});

describe("ReviewStudio 沉浸式书写", () => {
  beforeEach(() => { localStorage.clear(); });
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); document.documentElement.removeAttribute("data-theme"); });

  const DETAIL = {
    id: 7, title: "某作品", source: "bangumi", image_url: null, file_path: null,
    description: "", tags: [], characters: [], rating: null, my_rating: null,
  };
  const REVIEWS = [{ id: 1, title: "二刷", content: "**神作**，值得一看", rating: 9, status: "看完", spoiler: false, font_size: null, created_at: "2026-08-01T10:00:00", public_rating: null }];

  function mockFetch(reviews = REVIEWS, detail = DETAIL) {
    global.fetch = vi.fn((url, opts = {}) => {
      const u = String(url);
      const m = opts.method || "GET";
      if (u.includes("/detail")) return Promise.resolve({ ok: true, json: () => Promise.resolve(detail) });
      if (u.includes("/reviews") && m === "GET") return Promise.resolve({ ok: true, json: () => Promise.resolve(reviews) });
      if (u.includes("/reviews") && m === "POST") return Promise.resolve({ ok: true, json: () => Promise.resolve({ id: 9 }) });
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
    });
  }

  async function openStudio() {
    render(<ReviewStudio item={{ id: 7, title: "某作品" }} onClose={() => {}} />);
    await waitFor(() => expect(document.querySelector("textarea[placeholder*='支持 Markdown']")).toBeTruthy());
  }

  it("编辑器常驻（右侧），可切到预览", async () => {
    mockFetch();
    await openStudio();
    const ta = document.querySelector("textarea[placeholder*='支持 Markdown']");
    fireEvent.change(ta, { target: { value: "## 看完了\n\n这是一段**感想**" } });
    fireEvent.click(screen.getByText("预览"));
    await waitFor(() => expect(document.querySelector(".doc h2")).toBeTruthy());
    expect(document.querySelector(".doc h2").textContent).toBe("看完了");
    expect(document.querySelector(".doc strong").textContent).toBe("感想");
    fireEvent.click(screen.getByText("返回书写"));
    expect(document.querySelector("textarea[placeholder*='支持 Markdown']")).toBeTruthy();
  });

  it("工具栏：加粗围绕选区插入 Markdown 语法", async () => {
    mockFetch();
    await openStudio();
    const ta = document.querySelector("textarea[placeholder*='支持 Markdown']");
    fireEvent.change(ta, { target: { value: "这是重点" } });
    ta.setSelectionRange(2, 4);
    fireEvent.click(screen.getByTitle("加粗"));
    expect(ta.value).toBe("这是**重点**");
  });

  it("字号选择器改变编辑器正文字号", async () => {
    mockFetch();
    await openStudio();
    const ta = document.querySelector("textarea[placeholder*='支持 Markdown']");
    expect(ta.style.fontSize).toBe("15px");
    fireEvent.change(screen.getByTitle("正文字号"), { target: { value: "18" } });
    expect(ta.style.fontSize).toBe("18px");
  });

  it("引用卡：从正文提取 > 引用显示", async () => {
    mockFetch();
    await openStudio();
    const ta = document.querySelector("textarea[placeholder*='支持 Markdown']");
    fireEvent.change(ta, { target: { value: "正文\n\n> 命运石之门，选择吧。" } });
    await waitFor(() => expect(document.querySelector(".rs-quote").textContent).toContain("命运石之门，选择吧"));
  });

  it("Records 标签：已有书评按存储字号渲染为文档", async () => {
    mockFetch([{ id: 2, title: "二刷", content: "**神作**", rating: 9, status: "看完", spoiler: false, font_size: 18, created_at: "x", public_rating: null }]);
    render(<ReviewStudio item={{ id: 7, title: "某作品" }} onClose={() => {}} />);
    await waitFor(() => screen.getByText("Records"));
    fireEvent.click(screen.getByText("Records"));
    await waitFor(() => expect(screen.getByText("神作")).toBeTruthy());
    const doc = document.querySelector(".doc");
    expect(doc.style.fontSize).toBe("18px");
    expect(doc.querySelector("strong").textContent).toBe("神作");
  });

  it("Archive 标签：展示角色概念图", async () => {
    mockFetch([], { ...DETAIL, characters: [{ id: "c1", name: "库丽丝", relation: "主要角色", image_url: null }] });
    render(<ReviewStudio item={{ id: 7, title: "某作品" }} onClose={() => {}} />);
    await waitFor(() => screen.getByText("Archive"));
    fireEvent.click(screen.getByText("Archive"));
    await waitFor(() => expect(screen.getByText("库丽丝")).toBeTruthy());
  });

  it("三套主题下渲染且接入主题 token（无紫罗兰硬编码）", async () => {
    for (const theme of ["default", "mint", "sakura"]) {
      cleanup();
      document.documentElement.setAttribute("data-theme", theme);
      mockFetch();
      render(<ReviewStudio item={{ id: 7, title: "某作品" }} onClose={() => {}} />);
      const root = document.querySelector(".review-studio");
      expect(root).toBeTruthy();
      const html = root.outerHTML;
      // 上一轮的独立紫罗兰视觉已移除：不再有 --rs-* 变量与硬编码紫色
      expect(html).not.toContain("--rs-");
      expect(html).not.toContain("c084fc");
      // 接入全局主题 token
      expect(html).toContain("var(--text)");
      expect(html).toContain("var(--accent)");
      expect(html).toContain("var(--panel-border)");
    }
  });

  it("进入过渡与关闭过渡：先加 closing 类，再调用 onClose", async () => {
    const onClose = vi.fn();
    mockFetch();
    render(<ReviewStudio item={{ id: 7, title: "某作品" }} onClose={onClose} />);
    await waitFor(() => document.querySelector("textarea[placeholder*='支持 Markdown']"));
    // 进入：根元素带 rs-enter 动画类
    expect(document.querySelector(".review-studio").className).toContain("review-studio");
    fireEvent.click(screen.getByText("← 返回"));
    expect(document.querySelector(".review-studio").className).toContain("closing");
    expect(onClose).not.toHaveBeenCalled();
    await new Promise((r) => setTimeout(r, 250));
    expect(onClose).toHaveBeenCalled();
  });

  it("字数进度条随内容增长", async () => {
    mockFetch();
    await openStudio();
    const fill = document.querySelector(".rs-progress-fill");
    expect(fill.style.width).toBe("0%");
    fireEvent.change(document.querySelector("textarea[placeholder*='支持 Markdown']"),
      { target: { value: "x".repeat(250) } });
    expect(document.querySelector(".rs-progress-fill").style.width).toBe("50%");
  });
});
