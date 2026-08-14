// Phase 10-1-A-2：toast 引导 action（ToastHost 渲染 quiet 按钮，点击执行并立即消失）
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import React from "react";
import ToastHost from "../components/ToastHost.jsx";
import { toast, clearToasts } from "../toast.js";

afterEach(() => { cleanup(); clearToasts(); vi.restoreAllMocks(); });

describe("toast action（Phase 10-1-A-2）", () => {
  it("带 action 的 toast 渲染 quiet 按钮，点击触发回调并消失", async () => {
    const onClick = vi.fn();
    render(<ToastHost />);
    toast.success("已收藏「X」", 5000, { label: "去记录第一条回忆", onClick });
    const btn = await screen.findByText("去记录第一条回忆");
    expect(btn.tagName).toBe("BUTTON");
    expect(btn.getAttribute("type")).toBe("button");
    fireEvent.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByText("去记录第一条回忆")).toBeNull()); // 点击后立即消失
    expect(screen.queryByText("已收藏「X」")).toBeNull();
  });

  it("不带 action 的 toast 仍正常渲染（无回归）", async () => {
    render(<ToastHost />);
    toast.success("普通提示");
    expect(await screen.findByText("普通提示")).toBeTruthy();
    expect(screen.queryByText("去记录第一条回忆")).toBeNull();
  });
});
