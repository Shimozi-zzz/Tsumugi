// 角色图鉴冒烟：详情弹层渲染、角色墙渲染、点击角色看作品
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import CharacterWall from "../components/CharacterWall.jsx";
import ItemDetailPanel from "../components/ItemDetailPanel.jsx";

const WORK_A = { item_id: 1, title: "辉夜大小姐想让我告白", image_url: "https://img/a.jpg", source: "bangumi" };

const CHARS = [
  { id: 66899, name: "四宫辉夜", image_url: "https://img/huiye.jpg", relation: "主角",
    summary: "学生会副会长。", actors: ["古贺葵"], source: "bangumi", works: [WORK_A] },
  { id: 66900, name: "白银御行", image_url: "https://img/shiragami.jpg", relation: "主角",
    summary: "学生会长。", actors: [], source: "bangumi", works: [WORK_A] },
];

describe("CharacterWall", () => {
  beforeEach(() => {
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({ characters: CHARS }) })
    );
  });

  it("渲染角色卡片（立绘 + 名字）", async () => {
    render(<CharacterWall refreshKey={0} onOpenWork={() => {}} />);
    await waitFor(() => expect(screen.getByText("四宫辉夜")).toBeTruthy());
    expect(screen.getByText("白银御行")).toBeTruthy();
  });

  it("点击角色显示关联作品，点作品触发 onOpenWork", async () => {
    const onOpenWork = vi.fn();
    render(<CharacterWall refreshKey={0} onOpenWork={onOpenWork} />);
    await waitFor(() => screen.getByText("四宫辉夜"));
    fireEvent.click(screen.getByText("四宫辉夜"));
    // 出现"出自作品"区 + 作品名
    await waitFor(() => expect(screen.getByText("出自作品")).toBeTruthy());
    const workBtn = screen.getByText("辉夜大小姐想让我告白");
    expect(workBtn).toBeTruthy();
    fireEvent.click(workBtn);
    expect(onOpenWork).toHaveBeenCalledWith(WORK_A);
  });

  it("主列表为档案索引条目：mono 编目 + serif 人名 + quiet meta（非 pill/chip 堆叠）", async () => {
    const { container } = render(<CharacterWall refreshKey={0} onOpenWork={() => {}} />);
    await waitFor(() => screen.getByText("四宫辉夜"));
    const entries = container.querySelectorAll("button.char-entry");
    expect(entries.length).toBe(2);
    // mono 编目行 + serif 人名 + quiet meta
    expect(entries[0].querySelector(".char-entry-no")?.textContent).toMatch(/№\s*\d+/);
    expect(entries[0].querySelector(".char-entry-name")?.textContent).toBe("四宫辉夜");
    expect(entries[0].querySelector(".char-entry-cv")?.textContent).toContain("声优：");
    // 档案索引行存在
    expect(container.querySelector(".char-index")).toBeTruthy();
    // 条目内无 pill / chip-card（去 SaaS）
    expect(entries[0].querySelectorAll(".rounded-full, [class*=rounded-full]").length).toBe(0);
    // 选中详情内声优为 quiet mono 链接（无 pill 背景）
    fireEvent.click(screen.getByText("四宫辉夜"));
    await waitFor(() => expect(screen.getByText("古贺葵")).toBeTruthy());
    expect(screen.getByText("古贺葵").className).toContain("char-detail-actor");
  });

  it("无角色时显示空态引导", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({ characters: [] }) })
    );
    render(<CharacterWall refreshKey={0} onOpenWork={() => {}} />);
    await waitFor(() =>
      expect(screen.getByText(/还没有角色数据/)).toBeTruthy()
    );
  });
});

describe("ItemDetailPanel 统一 Work Detail（Phase 3-1 迁移自 ItemDetailModal）", () => {
  it("外部未收藏详情：渲染封面/简介/评分/角色墙 + 收藏入库", () => {
    render(
      <ItemDetailPanel
        externalDetail={{
          source: "bangumi", title: "辉夜大小姐想让我告白",
          description: "恋爱头脑战。", image_url: "https://img/a.jpg",
          rating: 8.9, tags: ["恋爱", "搞笑"],
          characters: [{ id: 1, name: "四宫辉夜", image_url: "https://img/h.jpg", relation: "主角" }],
        }}
        onSaveDetail={() => {}}
      />
    );
    expect(screen.getByText("辉夜大小姐想让我告白")).toBeTruthy();
    expect(screen.getByText(/大众 ★8.9/)).toBeTruthy(); // 收敛为 mono 编目行
    expect(screen.getByText("恋爱头脑战。")).toBeTruthy();
    expect(screen.getByText("四宫辉夜")).toBeTruthy();
    expect(screen.getByText("收藏入库")).toBeTruthy();
  });

  it("已收藏（saved）模式：进入我与它，不显示收藏入库", async () => {
    global.fetch = vi.fn((url) => {
      const u = String(url);
      if (u.includes("/detail")) return Promise.resolve({ ok: true, json: () => Promise.resolve({ id: 1, title: "X", source: "bangumi", characters: [], tags: [], description: "" }) });
      if (u.includes("/memories")) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (u.includes("/reviews")) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("我与它")).toBeTruthy());
    expect(screen.queryByText("收藏入库")).toBeNull();
  });

  it("Phase 10-1-A-1：零记录作品显示第一条记录引导", async () => {
    global.fetch = vi.fn((url) => {
      const u = String(url);
      if (u.includes("/detail")) return Promise.resolve({ ok: true, json: () => Promise.resolve({ id: 1, title: "X", source: "bangumi", characters: [], tags: [], description: "" }) });
      if (u.includes("/memories")) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (u.includes("/reviews")) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText(/还没有你的记录/)).toBeTruthy());
    // composer 仍在
    expect(screen.getByPlaceholderText(/写一句此刻的感想/)).toBeTruthy();
  });

  it("Phase 10-1-A-1：已有书评时不显示第一条记录引导", async () => {
    global.fetch = vi.fn((url) => {
      const u = String(url);
      if (u.includes("/detail")) return Promise.resolve({ ok: true, json: () => Promise.resolve({ id: 1, title: "X", source: "bangumi", characters: [], tags: [], description: "" }) });
      if (u.includes("/memories")) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (u.includes("/reviews")) return Promise.resolve({ ok: true, json: () => Promise.resolve([{ id: 10, content: "写过了", spoiler: false }]) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("我与它")).toBeTruthy());
    await waitFor(() => expect(screen.queryByText(/还没有你的记录/)).toBeNull());
  });

  it("未收藏时显示收藏按钮，点击触发 onSaveDetail", () => {
    const onSave = vi.fn();
    render(<ItemDetailPanel externalDetail={{ source: "bangumi", title: "X", characters: [] }} onSaveDetail={onSave} />);
    fireEvent.click(screen.getByText("收藏入库"));
    expect(onSave).toHaveBeenCalled();
  });
});
