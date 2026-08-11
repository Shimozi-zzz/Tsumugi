// 档案卡片（ADR 0054）：编目号、来源文字标注（非封面徽章）、档案占位、衬线标题、近直角容器
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import React from "react";
import ArchiveCard, { catalogNo, ArchivePlaceholder } from "../components/ArchiveCard.jsx";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const ITEM = { id: 3, title: "命运石之门", type: "external_ref", source: "bangumi", chunks_count: 1 };

describe("catalogNo", () => {
  it("按入库序号补零为 4 位", () => {
    expect(catalogNo({ id: 3 })).toBe("0003");
    expect(catalogNo({ id: 63 })).toBe("0063");
    expect(catalogNo({ id: 1000 })).toBe("1000");
  });
});

describe("ArchiveCard", () => {
  it("编目行：NO. + 来源文字标注（来源不在封面图上）", () => {
    const { container } = render(<ArchiveCard it={ITEM} cover={null} onOpen={() => {}} />);
    expect(screen.getByText("NO. 0003")).toBeTruthy();
    expect(screen.getByText("bangumi")).toBeTruthy(); // 来源为文字标注
    // 封面容器内不应再有来源徽章（色块 pill 已移除）
    const cover = container.querySelector(".archive-card-cover");
    expect(cover.querySelector('span[style*="backgroundColor"]')).toBeNull();
    // 编目行在信息区（cover 之外）
    expect(container.querySelector(".archive-card-meta")).toBeTruthy();
  });

  it("标题用衬线（tsm-heading）+ 大字重；容器近直角圆角小", () => {
    const { container } = render(<ArchiveCard it={ITEM} cover={null} onOpen={() => {}} />);
    const title = container.querySelector(".archive-card-title");
    expect(title.textContent).toBe("命运石之门");
    expect(title.className).toContain("tsm-heading");
    expect(container.querySelector(".archive-card").style.borderRadius).toBeFalsy(); // radius 走 CSS 类非内联
  });

  it("无封面 → 档案占位（书脊轮廓 + 编目号），不是空白灰块", () => {
    const { container } = render(<ArchiveCard it={ITEM} cover={null} onOpen={() => {}} />);
    const ph = container.querySelector('[data-testid="archive-placeholder"]');
    expect(ph).toBeTruthy();
    expect(ph.querySelector(".archive-ph-spine")).toBeTruthy();   // 书脊轮廓
    expect(ph.textContent).toContain("藏 · 0003");                // 编目号填充
  });

  it("有封面 → 正常渲染图片，无占位", () => {
    const { container } = render(<ArchiveCard it={ITEM} cover="https://x/1.jpg" onOpen={() => {}} />);
    expect(container.querySelector(".archive-card-img")).toBeTruthy();
    expect(container.querySelector('[data-testid="archive-placeholder"]')).toBeNull();
  });

  it("点击/右键/书评/删除/选择模式交互", () => {
    const onOpen = vi.fn(), onCtx = vi.fn(), onReview = vi.fn(), onDelete = vi.fn();
    const { container } = render(<ArchiveCard it={ITEM} cover={null}
      onOpen={onOpen} onContextMenu={onCtx} onReview={onReview} onDelete={onDelete} />);
    fireEvent.click(container.querySelector(".archive-card"));
    expect(onOpen).toHaveBeenCalled();
    fireEvent.contextMenu(container.querySelector(".archive-card"));
    expect(onCtx).toHaveBeenCalled();
    fireEvent.click(screen.getByText("书评"));
    expect(onReview).toHaveBeenCalled();
    fireEvent.click(screen.getByText("删除"));
    expect(onDelete).toHaveBeenCalled();
  });

  it("选择模式：点击触发 onToggleSelect 而非 onOpen", () => {
    const onOpen = vi.fn(), onToggle = vi.fn();
    const { container } = render(<ArchiveCard it={ITEM} cover={null} onOpen={onOpen}
      selectMode onToggleSelect={onToggle} selected />);
    fireEvent.click(container.querySelector(".archive-card"));
    expect(onToggle).toHaveBeenCalled();
    expect(onOpen).not.toHaveBeenCalled();
    expect(container.querySelector(".archive-card").className).toContain("archive-card-selected");
  });

  it("索书卡密集元数据行（编目抽屉签名）：─ 编目号 / ─ 来源 / ─ 记录", () => {
    const { container } = render(<ArchiveCard it={ITEM} cover={null} onOpen={() => {}} />);
    const lines = container.querySelector('[data-testid="archive-card-lines"]');
    expect(lines).toBeTruthy();
    expect(lines.textContent).toContain("─ 编目号 0003");
    expect(lines.textContent).toContain("─ 来源 bangumi");
    expect(lines.textContent).toContain("─ 记录 1 条");
  });

  it("本地笔记不显示来源标注", () => {
    render(<ArchiveCard it={{ id: 1, title: "笔记", type: "note", source: "local" }} cover={null} onOpen={() => {}} />);
    expect(screen.queryByText("local")).toBeNull();
  });
});

describe("ArchivePlaceholder 直接渲染", () => {
  it("含书脊轮廓线与编目号", () => {
    const { container } = render(<ArchivePlaceholder no="0003" />);
    expect(container.querySelector(".archive-ph-spine")).toBeTruthy();
    expect(container.querySelector(".archive-ph-no").textContent).toContain("藏 · 0003");
  });
});
