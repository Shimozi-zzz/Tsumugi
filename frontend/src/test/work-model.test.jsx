// P1 Work 模型（ADR 0045）：作品类型/原名/发行展示、详情页内联编辑、图书馆类型筛选、命令面板
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import React from "react";
import ItemDetailPanel from "../components/ItemDetailPanel.jsx";
import DesktopView from "../components/DesktopView.jsx";
import { itemInfoRows } from "../components/ui.jsx";
import { buildCommands } from "../commands.js";

function ok(payload, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(payload) });
}

const DETAIL = { id: 1, title: "空之境界", source: "bangumi", description: "简介", rating: 8.9,
  my_rating: null, tags: ["科幻"], reference_text: "", social: {}, raw_metadata: null, characters: [],
  image_url: null, file_path: null, work_type: "anime", alternative_title: "空の境界", release_date: "2008-02-09",
  collection_status: "看完", collected_at: "2026-08-01T10:00:00", favorite: true };

function mockFetch({ items = [], detail = DETAIL, workTypePatch = null, collections = [] } = {}) {
  global.fetch = vi.fn((url, opts = {}) => {
    const u = String(url);
    const m = opts.method || "GET";
    const dm = u.match(/\/items\/(\d+)\/detail$/);
    if (dm) return ok(detail);
    const dw = u.match(/\/items\/(\d+)\/work$/);
    if (dw && m === "PATCH") {
      const body = JSON.parse(opts.body || "{}");
      return ok({ ...detail, work_type: body.work_type === "" ? null : (body.work_type ?? detail.work_type) });
    }
    const dc = u.match(/\/items\/(\d+)\/collection$/);
    if (dc && m === "PATCH") {
      const body = JSON.parse(opts.body || "{}");
      return ok({ ...detail,
        collection_status: body.status === "" ? null : (body.status ?? detail.collection_status),
        favorite: body.favorite ?? detail.favorite });
    }
    if (u.includes("/collections")) return ok(collections);
    if (u.includes("/memories")) return ok([]);
    if (u.includes("/reviews")) return ok([]);
    if (u.includes("/items") && m === "GET") return ok({ total: items.length, items });
    if (u.includes("/tags")) return ok([]);
    if (u.includes("/connectors")) return ok([]);
    if (u.includes("/plugins")) return ok({ plugins: [], failures: [], notice_needed: false, plugin_dir: "./plugins" });
    return ok({});
  });
}

beforeEach(() => { localStorage.clear(); document.documentElement.removeAttribute("data-theme"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("itemInfoRows 世界轴列", () => {
  it("优先用列字段展示 类型/原名/发行日期（回退 meta）", () => {
    const rows = itemInfoRows(DETAIL);
    const get = (l) => rows.find((r) => r.label === l)?.value;
    expect(get("类型")).toBe("动画");
    expect(get("原名")).toBe("空の境界");
    expect(get("发行日期")).toBe("2008-02-09");
  });

  it("无世界轴信息时不产生类型行", () => {
    const rows = itemInfoRows({ id: 1, title: "x", source: "local" });
    expect(rows.find((r) => r.label === "类型")).toBeUndefined();
  });
});

describe("详情页内联编辑（外部世界区）", () => {
  it("外部作品显示类型下拉，修改后调用 PATCH 并更新", async () => {
    mockFetch();
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("空之境界")).toBeTruthy());
    const sel = screen.getByTitle("作品类型（可手动修正）");
    await waitFor(() => expect(sel.value).toBe("anime"));
    fireEvent.change(sel, { target: { value: "galgame" } });
    await waitFor(() => expect(sel.value).toBe("galgame"));
    const patchCall = global.fetch.mock.calls.find((c) => String(c[0]).includes("/work"));
    expect(patchCall).toBeTruthy();
    expect(JSON.parse(patchCall[1].body)).toEqual({ work_type: "galgame" });
  });

  it("本地笔记不显示类型下拉", async () => {
    mockFetch({ detail: { ...DETAIL, source: "local", work_type: null } });
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("空之境界")).toBeTruthy());
    expect(screen.queryByTitle("作品类型（可手动修正）")).toBeNull();
  });

  it("我的记录区：收藏状态/喜欢 内联编辑（P2），修改调用 PATCH", async () => {
    mockFetch();
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByTitle("收藏状态（可手动修正）")).toBeTruthy());
    // 收藏时间展示
    expect(screen.getByText(/收藏于 2026-08-01/)).toBeTruthy();
    const sel = screen.getByTitle("收藏状态（可手动修正）");
    await waitFor(() => expect(sel.value).toBe("看完"));
    fireEvent.change(sel, { target: { value: "搁置" } });
    await waitFor(() => expect(sel.value).toBe("搁置"));
    const patchCall = global.fetch.mock.calls.find((c) => String(c[0]).includes("/collection"));
    expect(patchCall).toBeTruthy();
    expect(JSON.parse(patchCall[1].body)).toEqual({ status: "搁置" });
    // 喜欢 toggle
    fireEvent.click(screen.getByTitle("是否喜欢"));
    await waitFor(() => expect(global.fetch.mock.calls.some((c) => String(c[0]).includes("/collection") && JSON.parse(c[1].body).favorite === false)).toBeTruthy());
  });

  it("本地笔记不显示收藏编辑区", async () => {
    mockFetch({ detail: { ...DETAIL, source: "local", collection_status: null, favorite: false, collected_at: null } });
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("空之境界")).toBeTruthy());
    expect(screen.queryByTitle("收藏状态（可手动修正）")).toBeNull();
  });
});

describe("图书馆按类型筛选（P1）", () => {
  const ITEMS = [
    { id: 1, title: "空之境界", type: "external_ref", source: "bangumi", work_type: "anime", tags: [], chunks_count: 1 },
    { id: 2, title: "Clannad", type: "external_ref", source: "bangumi", work_type: "anime", tags: [], chunks_count: 1 },
    { id: 3, title: "白色相簿2", type: "external_ref", source: "bangumi", work_type: "galgame", tags: [], chunks_count: 1 },
  ];
  it("出现类型 chips，点击筛选只留该类型", async () => {
    mockFetch({ items: ITEMS });
    render(<DesktopView
      items={ITEMS} total={3} allTags={[]} refresh={() => {}}
      theme="default" setTheme={() => {}}
      custom={{ accentHue: 0, density: "comfortable", radius: 16 }} updateCustom={() => {}}
      textOverlays={[]} updateTextOverlays={() => {}} />);
    fireEvent.click(screen.getByTitle("书库"));
    await waitFor(() => expect(screen.getByText("全部类型")).toBeTruthy());
    // chips：动画 / Galgame
    fireEvent.click(screen.getByText("Galgame"));
    await waitFor(() => expect(screen.getByText("白色相簿2")).toBeTruthy());
    expect(screen.queryByText("空之境界")).toBeNull();
    // 取消筛选回全部
    fireEvent.click(screen.getByText("Galgame"));
    await waitFor(() => expect(screen.getByText("空之境界")).toBeTruthy());
  });
});

describe("命令面板 work_type 关键词", () => {
  it("条目关键词含 work_type（可搜 'galgame' 找到条目）", () => {
    const ctx = { items: [{ id: 1, title: "白色相簿2", source: "bangumi", type: "external_ref", work_type: "galgame" }], tags: [], section: () => {} };
    const cmds = buildCommands(ctx);
    const it = cmds.find((c) => c.id === "item-1");
    expect(it.keywords.join(" ")).toContain("galgame");
  });
});

describe("作品详情丰富资料（Phase 11-B/C）", () => {
  it("显示 题材/状态/Staff/Relations；空字段隐藏", async () => {
    mockFetch({ detail: { ...DETAIL,
      genres: ["科幻", "悬疑"], status: "FINISHED",
      staff: [{ name: "Takuya Sato", role: "Director" }],
      relations: [{ relation: "SEQUEL", title: "Steins;Gate 0", source: "anilist" }],
      background: "https://x/b.png" } });
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("空之境界")).toBeTruthy());
    expect(screen.getByText(/悬疑/)).toBeTruthy();     // genres（DETAIL.tags 只有"科幻"，悬疑仅在 genres）
    expect(screen.getByText("FINISHED")).toBeTruthy();  // status
    expect(screen.getByText(/Staff/)).toBeTruthy();         // staff
    expect(screen.getByText(/Takuya Sato/)).toBeTruthy();
    expect(screen.getByText(/Relations/)).toBeTruthy();      // relations
    expect(screen.getByText(/Steins;Gate 0/)).toBeTruthy();
  });

  it("空字段正常隐藏（旧数据兼容）", async () => {
    mockFetch({ detail: DETAIL });  // 无 genres/staff/relations
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("空之境界")).toBeTruthy());
    expect(screen.queryByText(/Staff/)).toBeNull();
    expect(screen.queryByText(/Relations/)).toBeNull();
  });

  it("Hero 显示原名/年份与多来源徽标（Phase 11-D）", async () => {
    mockFetch({ detail: { ...DETAIL,
      sources: [{ source: "bangumi", external_id: "1" }, { source: "anilist", external_id: "2" }] } });
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText("空之境界")).toBeTruthy());
    expect(screen.getAllByText("空の境界").length).toBeGreaterThan(0);  // 原名（hero + 编目行）
    expect(screen.getAllByText(/2008/).length).toBeGreaterThan(0);       // 年份（hero meta + 编目日期）
    expect(screen.getAllByText("Bangumi").length).toBeGreaterThan(0);
    expect(screen.getAllByText("AniList").length).toBeGreaterThan(0);
  });

  it("Relations 分组并支持本地跳转/外部链接（Phase 12-D）", async () => {
    const opened = [];
    mockFetch({ detail: { ...DETAIL, relations: [
      { relation_type: "sequel", title: "续作A", target_media_id: 99, target_item_id: 7, is_local: true },
      { relation_type: "spin_off", title: "外传B", target_media_id: null, external_url: "https://x/b" },
    ] } });
    render(<ItemDetailPanel itemId={1} onOpenRelated={(id) => opened.push(id)} />);
    await waitFor(() => expect(screen.getByText("空之境界")).toBeTruthy());
    expect(screen.getByText("后作")).toBeTruthy();   // 分组标签（sequel）
    expect(screen.getByText("衍生")).toBeTruthy();   // 分组标签（spin_off）
    fireEvent.click(screen.getByText("续作A"));      // 本地关系 → onOpenRelated(target_item_id)
    expect(opened).toEqual([7]);
    expect(screen.getByText("外传B").closest("a")).toBeTruthy();  // 外部关系 → 链接
  });

  it("Staff 同人合并角色徽标（Phase 12-D）", async () => {
    mockFetch({ detail: { ...DETAIL, staff: [
      { name: "Takuya Sato", role: "Director" },
      { name: "Takuya Sato", role: "Writer" },
      { name: "Writer A", role: "Writer" },
    ] } });
    render(<ItemDetailPanel itemId={1} />);
    await waitFor(() => expect(screen.getByText(/Staff/)).toBeTruthy());
    expect(screen.getAllByText("Takuya Sato").length).toBe(1);  // 同人合并为一行
    expect(screen.getByText("Director / Writer")).toBeTruthy(); // 角色徽标合并
  });
});
