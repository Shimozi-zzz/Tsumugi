// Bangumi 面板：OAuth 引导 / 已连接状态 / 批量导入进度摘要
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import React from "react";
import BangumiPanel from "../components/BangumiPanel.jsx";
import ToastHost from "../components/ToastHost.jsx";
import { clearToasts } from "../toast.js";

function ok(payload) {
  return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
}

describe("BangumiPanel", () => {
  beforeEach(() => { localStorage.clear(); clearToasts(); });
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

  it("未配置凭证时显示注册引导与表单", async () => {
    global.fetch = vi.fn((u) => {
      if (String(u).includes("/bangumi/oauth/status")) {
        return ok({ connected: false, config_configured: false, redirect_uri: "http://x" });
      }
      return ok({});
    });
    render(<BangumiPanel />);
    expect(await screen.findByText(/注册一个应用/)).toBeTruthy();
    expect(screen.getByPlaceholderText("client_id")).toBeTruthy();
    expect(screen.getByPlaceholderText("client_secret")).toBeTruthy();
  });

  it("已连接时显示连接状态 + 批量导入按钮", async () => {
    global.fetch = vi.fn((u) => {
      if (String(u).includes("/bangumi/oauth/status")) {
        return ok({ connected: true, config_configured: true, user_id: "u1", expires_at: 9999999999 });
      }
      return ok({});
    });
    render(<BangumiPanel />);
    await waitFor(() => expect(screen.getByText("已连接")).toBeTruthy());
    expect(screen.getByText("批量导入我的收藏")).toBeTruthy();
    expect(screen.getByText("断开连接")).toBeTruthy();
  });

  it("批量导入：轮询进度并显示结果摘要", async () => {
    const callCount = { n: 0 };
    global.fetch = vi.fn((u) => {
      const url = String(u);
      if (url.includes("/bangumi/oauth/status")) {
        return ok({ connected: true, config_configured: true });
      }
      if (url.includes("/bangumi/import/status")) {
        callCount.n += 1;
        if (callCount.n === 1) {
          return ok({ job_id: "j1", state: "running", total: 10, current: 5, imported: 5, skipped: 1, failed: 0, failures: [] });
        }
        return ok({ job_id: "j1", state: "done", total: 10, current: 10, imported: 10, skipped: 0, failed: 0, failures: [], message: "导入 10 条" });
      }
      if (url.includes("/bangumi/import")) return ok({ job_id: "j1" });
      return ok({});
    });
    render(<><BangumiPanel /><ToastHost /></>);
    await waitFor(() => expect(screen.getByText("已连接")).toBeTruthy());

    vi.useFakeTimers();
    fireEvent.click(screen.getByText("批量导入我的收藏"));
    await vi.advanceTimersByTimeAsync(900); // 第一次轮询：running
    await vi.advanceTimersByTimeAsync(900); // 第二次轮询：done
    expect(screen.getByText(/已导入 10 \/ 10/)).toBeTruthy();
    expect(screen.getByText("100%")).toBeTruthy();
    expect(screen.getByText(/导入 10 条/)).toBeTruthy(); // 完成 toast
  });
});
