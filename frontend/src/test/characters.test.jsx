// 角色图鉴冒烟：详情弹层渲染、角色墙渲染、点击角色看作品
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import CharacterWall from "../components/CharacterWall.jsx";
import ItemDetailModal from "../components/ItemDetailModal.jsx";

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

describe("ItemDetailModal", () => {
  it("渲染封面/简介/评分/角色墙", () => {
    render(
      <ItemDetailModal
        detail={{
          source: "bangumi", title: "辉夜大小姐想让我告白",
          description: "恋爱头脑战。", image_url: "https://img/a.jpg",
          rating: 8.9, tags: ["恋爱", "搞笑"],
          characters: [{ id: 1, name: "四宫辉夜", image_url: "https://img/h.jpg", relation: "主角" }],
        }}
        saved={false} onClose={() => {}} onSave={() => {}}
      />
    );
    expect(screen.getByText("辉夜大小姐想让我告白")).toBeTruthy();
    expect(screen.getByText("大众 ★8.9")).toBeTruthy();
    expect(screen.getByText("恋爱头脑战。")).toBeTruthy();
    expect(screen.getByText("四宫辉夜")).toBeTruthy();
    expect(screen.getByText("登场角色")).toBeTruthy();
  });

  it("saved=true 显示已收藏，saved=true 不显示收藏按钮", () => {
    render(
      <ItemDetailModal
        detail={{ source: "bangumi", title: "X", characters: [] }}
        saved={true} onClose={() => {}}
      />
    );
    expect(screen.getByText("已收藏")).toBeTruthy();
    expect(screen.queryByText("收藏入库")).toBeNull();
  });

  it("未收藏时显示收藏按钮，点击触发 onSave", () => {
    const onSave = vi.fn();
    render(
      <ItemDetailModal
        detail={{ source: "bangumi", title: "X", characters: [] }}
        saved={false} onClose={() => {}} onSave={onSave}
      />
    );
    fireEvent.click(screen.getByText("收藏入库"));
    expect(onSave).toHaveBeenCalled();
  });
});
