// P1 Work 模型（ADR 0045）：作品类型/原名/发行展示、详情页内联编辑、图书馆类型筛选、命令面板
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import React from "react";
import ItemDetailPanel from "../components/ItemDetailPanel.jsx";
import DesktopView from "../components/DesktopView.jsx";
import PersonPanel from "../components/PersonPanel.jsx";
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

  it("本地关系目标缺失（target_item_id null）回退外部链接（Phase 13-E）", async () => {
    const opened = [];
    mockFetch({ detail: { ...DETAIL, relations: [
      { relation_type: "sequel", title: "孤儿目标", target_media_id: 99, target_item_id: null,
        is_local: true, external_url: "https://myanimelist.net/anime/888" },
    ] } });
    render(<ItemDetailPanel itemId={1} onOpenRelated={(id) => opened.push(id)} />);
    await waitFor(() => expect(screen.getByText("空之境界")).toBeTruthy());
    const row = screen.getByText("孤儿目标").closest("a"); // 回退为外部链接而非本地死按钮
    expect(row).toBeTruthy();
    expect(row.getAttribute("href")).toBe("https://myanimelist.net/anime/888");
    expect(screen.getByText("本地")).toBeTruthy(); // 仍标记本地（MediaEntry 存在）
    fireEvent.click(screen.getByText("孤儿目标"));
    expect(opened).toEqual([]); // 不触发本地跳转
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


describe("人物导航（Phase 13-B）", () => {
  it("Staff 行可点击打开人物面板", async () => {
    const opened = [];
    mockFetch({ detail: { ...DETAIL, staff: [
      { name: "Takuya Sato", role: "Director", source: "anilist", external_id: "5" }] } });
    render(<ItemDetailPanel itemId={1} onOpenPerson={(p) => opened.push(p)} />);
    await waitFor(() => expect(screen.getByText(/Staff/)).toBeTruthy());
    fireEvent.click(screen.getByText("Takuya Sato"));
    expect(opened).toEqual([{ type: "staff", source: "anilist", external_id: "5", name: "Takuya Sato" }]);
  });

  it("角色卡可点击打开人物面板", async () => {
    const opened = [];
    mockFetch({ detail: { ...DETAIL, characters: [
      { id: "c1", name: "角色A", relation: "主角" }] } });
    render(<ItemDetailPanel itemId={1} onOpenPerson={(p) => opened.push(p)} />);
    await waitFor(() => expect(screen.getByText("角色A")).toBeTruthy());
    fireEvent.click(screen.getByText("角色A"));
    expect(opened).toEqual([{ type: "character", source: "bangumi", external_id: "c1", name: "角色A" }]);
  });
});


describe("PersonPanel 身份区分（Phase 13-C）", () => {
  it("Staff 面板显示聚合身份 roles 且作品可点击", async () => {
    global.fetch = vi.fn((u) => {
      const url = String(u);
      if (url.includes("/staff/anilist/5")) return ok({
        source: "anilist", external_id: "5", name: "Takuya Sato",
        works: [
          { media_id: 1, item_id: 10, title: "作品A", role: "监督", year: 2011, work_type: "anime" },
          { media_id: 2, item_id: 11, title: "作品B", role: "原作", year: 2013, work_type: "manga" },
        ],
      });
      return ok({});
    });
    const opened = [];
    render(<PersonPanel person={{ type: "staff", source: "anilist", external_id: "5", name: "Takuya Sato" }}
      onOpenWork={(id) => opened.push(id)} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("身份：监督 / 原作")).toBeTruthy());
    fireEvent.click(screen.getByText("作品A"));
    expect(opened).toEqual([10]);
  });

  it("Character 面板显示身份/CV 且作品可点击", async () => {
    global.fetch = vi.fn((u) => {
      const url = String(u);
      if (url.includes("/characters/bangumi/c1")) return ok({
        source: "bangumi", external_id: "c1", name: "角色A", image_url: null,
        relation: "主角", actors: ["声优X"], summary: "简介",
        works: [{ media_id: null, item_id: 10, title: "作品A", work_type: "anime" }],
      });
      return ok({});
    });
    const opened = [];
    render(<PersonPanel person={{ type: "character", source: "bangumi", external_id: "c1", name: "角色A" }}
      onOpenWork={(id) => opened.push(id)} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/CV：声优X/)).toBeTruthy());
    expect(screen.getByText("关系：主角")).toBeTruthy();
    fireEvent.click(screen.getByText("作品A"));
    expect(opened).toEqual([10]);
  });
});


describe("探索闭环返回路径（Phase 13-D）", () => {
  const PROPS = { items: [], total: 0, allTags: [], refresh: () => {},
    theme: "default", setTheme: () => {},
    custom: { accentHue: 0, density: "comfortable", radius: 16 }, updateCustom: () => {},
    textOverlays: [], updateTextOverlays: () => {} };

  it("人物 → 作品 → 返回人物：上下文保留且不重复请求", async () => {
    let staffCalls = 0;
    global.fetch = vi.fn((u, opts = {}) => {
      const url = String(u);
      const m = opts.method || "GET";
      if (url.includes("/items") && m === "GET" && !/\/items\/\d+/.test(url)) return ok({ total: 1, items: [
        { id: 1, title: "作品A", type: "external_ref", source: "anilist", tags: [], image_url: null }] });
      if (/\/items\/1\/detail$/.test(url)) return ok({
        id: 1, title: "作品A", source: "anilist", description: "简介", tags: [],
        characters: [], relations: [], sources: [], image_url: null, work_type: "anime",
        staff: [{ name: "Takuya Sato", role: "Director", source: "anilist", external_id: "5" }],
        collection_status: null, collected_at: null, favorite: false });
      if (/\/items\/10\/detail$/.test(url)) return ok({
        id: 10, title: "作品B", source: "anilist", description: "简介B", tags: [],
        characters: [], relations: [], sources: [], image_url: null, work_type: "anime",
        staff: [], collection_status: null, collected_at: null, favorite: false });
      if (url.includes("/staff/anilist/5")) {
        staffCalls += 1;
        return ok({
          source: "anilist", external_id: "5", name: "Takuya Sato",
          works: [{ media_id: 1, item_id: 10, title: "作品B", role: "Director", work_type: "anime" }] });
      }
      if (url.includes("/tags")) return ok([]);
      if (url.includes("/connectors")) return ok([]);
      if (url.includes("/collections")) return ok([]);
      if (url.includes("/reviews")) return ok([]);
      if (url.includes("/memories")) return ok([]);
      if (url.includes("/plugins")) return ok({ plugins: [], failures: [], notice_needed: false, plugin_dir: "./plugins" });
      return ok({});
    });
    render(<DesktopView {...PROPS} />);
    // Library → 打开作品 A
    fireEvent.click(screen.getByTitle("书库"));
    await waitFor(() => expect(screen.getByText("作品A")).toBeTruthy());
    fireEvent.click(screen.getByText("作品A"));
    await waitFor(() => expect(screen.getByText("作品档案")).toBeTruthy());
    // Staff 行 → PersonPanel
    fireEvent.click(screen.getByText("Takuya Sato"));
    await waitFor(() => expect(screen.getByText("相关作品 · 1")).toBeTruthy());
    expect(staffCalls).toBe(1);
    // 人物面板作品 → 打开 ItemDetailPanel（人物面板保留在下方）
    fireEvent.click(screen.getByText("作品B"));
    await waitFor(() => expect(screen.getByText("NO. 0010")).toBeTruthy());
    expect(screen.getByText("相关作品 · 1")).toBeTruthy(); // 上下文未丢失
    expect(staffCalls).toBe(1); // 未重复请求人物数据
    // 「返回人物」→ 详情关闭，人物面板仍在
    fireEvent.click(screen.getByTitle("返回人物面板"));
    await waitFor(() => expect(screen.queryByText("NO. 0010")).toBeNull());
    expect(screen.getByText("相关作品 · 1")).toBeTruthy();
    expect(staffCalls).toBe(1);
  });
});
