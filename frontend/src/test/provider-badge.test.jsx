// ProviderBadge 多来源徽标（Phase 11-A/B）：多来源聚合显示 + 单源回退 + 数量
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import React from "react";
import { ProviderBadge } from "../components/ui.jsx";

afterEach(() => cleanup());

describe("ProviderBadge", () => {
  it("多来源显示徽标列表与数量", () => {
    render(<ProviderBadge source="bangumi"
      sources={[{ source: "bangumi" }, { source: "anilist" }]} count />);
    expect(screen.getByText("Bangumi")).toBeTruthy();
    expect(screen.getByText("AniList")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
  });

  it("无 sources 时回退单源（旧客户端兼容）", () => {
    render(<ProviderBadge source="vndb" />);
    expect(screen.getByText("VNDB")).toBeTruthy();
  });

  it("未知来源显示原始 key", () => {
    render(<ProviderBadge source="my-source" />);
    expect(screen.getByText("my-source")).toBeTruthy();
  });
});
