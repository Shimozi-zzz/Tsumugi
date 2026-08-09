// 看守猫娘台词库（ADR 0040）：场景匹配、随机选取、台词库结构与人设合规
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  MASCOT_LINES, MILESTONES, WINDOWS_MS,
  pickLine, matchScene, selectLine,
  computeLastVisitGap, resetMascotSession,
} from "../mascot.js";

function isoHoursAgo(h) {
  return new Date(Date.now() - h * 60 * 60 * 1000).toISOString();
}
function ctx(overrides = {}) {
  return {
    hour: 10,
    collectionCount: 5,
    reviewCount: 0,
    newestCollectionAt: null,
    newestReviewAt: null,
    lastVisitGap: 0,
    ...overrides,
  };
}

beforeEach(() => { localStorage.clear(); resetMascotSession(); });
afterEach(() => { vi.restoreAllMocks(); });

describe("matchScene（场景匹配）", () => {
  it("距上次打开超过 3 天 → 想念（优先级最高）", () => {
    expect(matchScene(ctx({ lastVisitGap: 4 * 24 * 60 * 60 * 1000 }))).toEqual({ scene: "missing_you" });
    // 即使刚有新收藏，久别重逢的想念仍优先
    expect(matchScene(ctx({ lastVisitGap: 4 * 24 * 60 * 60 * 1000, newestCollectionAt: isoHoursAgo(1) })))
      .toEqual({ scene: "missing_you" });
    // 3 天以内不触发
    expect(matchScene(ctx({ lastVisitGap: 2 * 24 * 60 * 60 * 1000 })).scene).not.toBe("missing_you");
  });

  it("收藏/书评数恰好落在里程碑 → milestone（优先于新收藏/写书评）", () => {
    expect(matchScene(ctx({ collectionCount: 100 }))).toEqual({ scene: "milestone", variant: "collection:100" });
    expect(matchScene(ctx({ reviewCount: 10 }))).toEqual({ scene: "milestone", variant: "review:10" });
    // 100 件收藏 + 刚收藏新作品 → 庆祝里程碑
    expect(matchScene(ctx({ collectionCount: 100, newestCollectionAt: isoHoursAgo(1) })).scene).toBe("milestone");
    // 不在节点上 → 不是里程碑
    expect(matchScene(ctx({ collectionCount: 101 })).scene).not.toBe("milestone");
    expect(matchScene(ctx({ collectionCount: 0, reviewCount: 0 })).scene).not.toBe("milestone");
  });

  it("最近 6 小时内新收藏 → new_collection", () => {
    expect(matchScene(ctx({ newestCollectionAt: isoHoursAgo(1) }))).toEqual({ scene: "new_collection" });
    expect(matchScene(ctx({ newestCollectionAt: isoHoursAgo(5.9) }))).toEqual({ scene: "new_collection" });
    // 超过窗口 → 不触发
    expect(matchScene(ctx({ newestCollectionAt: isoHoursAgo(6.1) })).scene).not.toBe("new_collection");
    // 无收藏 → 不触发
    expect(matchScene(ctx({ newestCollectionAt: null })).scene).not.toBe("new_collection");
  });

  it("最近 6 小时内写过书评 → wrote_review（新收藏优先于书评）", () => {
    expect(matchScene(ctx({ newestReviewAt: isoHoursAgo(1) }))).toEqual({ scene: "wrote_review" });
    expect(matchScene(ctx({ newestReviewAt: isoHoursAgo(6.1) })).scene).not.toBe("wrote_review");
    // 同时有新收藏 → 新收藏优先
    expect(matchScene(ctx({ newestCollectionAt: isoHoursAgo(1), newestReviewAt: isoHoursAgo(1) })).scene)
      .toBe("new_collection");
  });

  it("无特殊事件 → 按时段问候（清晨/午后/傍晚/深夜）", () => {
    expect(matchScene(ctx({ hour: 7 }))).toEqual({ scene: "greeting", variant: "morning" });
    expect(matchScene(ctx({ hour: 14 }))).toEqual({ scene: "greeting", variant: "afternoon" });
    expect(matchScene(ctx({ hour: 20 }))).toEqual({ scene: "greeting", variant: "evening" });
    expect(matchScene(ctx({ hour: 0 }))).toEqual({ scene: "greeting", variant: "night" });
    expect(matchScene(ctx({ hour: 4 }))).toEqual({ scene: "greeting", variant: "night" });
    expect(matchScene(ctx({ hour: 23 }))).toEqual({ scene: "greeting", variant: "night" });
  });

  it("hour 未知 → fallback 兜底", () => {
    expect(matchScene(ctx({ hour: undefined }))).toEqual({ scene: "fallback" });
    expect(matchScene({})).toEqual({ scene: "fallback" });
  });
});

describe("selectLine / pickLine（随机选取）", () => {
  it("pickLine 返回列表内的一句", () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    expect(pickLine(["甲", "乙"])).toBe("甲");
    vi.spyOn(Math, "random").mockReturnValue(0.99);
    expect(pickLine(["甲", "乙"])).toBe("乙");
    expect(pickLine([])).toBe("");
  });

  it("selectLine 按场景取对应台词库，缺库兜底 fallback", () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    expect(MASCOT_LINES.new_collection).toContain(selectLine({ scene: "new_collection" }));
    expect(MASCOT_LINES.milestones["collection:100"]).toContain(selectLine({ scene: "milestone", variant: "collection:100" }));
    expect(MASCOT_LINES.greeting.morning).toContain(selectLine({ scene: "greeting", variant: "morning" }));
    expect(MASCOT_LINES.fallback).toContain(selectLine({ scene: "missing_key" }));
    expect(MASCOT_LINES.fallback).toContain(selectLine(null));
  });

  it("missing_you 场景 → 选中句确实来自想念库", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.5);
    const line = selectLine({ scene: "missing_you" });
    expect(MASCOT_LINES.missing_you).toContain(line);
  });
});

describe("computeLastVisitGap（想念判定数据）", () => {
  it("首次读取上次打开时间并写入本次；模块级缓存只算一次（StrictMode 防双跑）", () => {
    expect(computeLastVisitGap()).toBe(0); // 无记录
    expect(localStorage.getItem("tsumugi-mascot-last-visit")).toBeTruthy();
    // 模拟上次打开是 4 天前：直接写旧时间戳，再读应得 4 天
    localStorage.setItem("tsumugi-mascot-last-visit", String(Date.now() - 4 * 24 * 60 * 60 * 1000));
    resetMascotSession();
    const gap = computeLastVisitGap();
    expect(gap).toBeGreaterThan(WINDOWS_MS.missingDays);
    expect(gap).toBeLessThan(5 * 24 * 60 * 60 * 1000);
    // 同页会话内再次调用不重算（缓存）
    const second = computeLastVisitGap();
    expect(second).toBe(gap);
  });
});

describe("台词库结构与人设合规", () => {
  const allLineLists = [
    ...Object.values(MASCOT_LINES.greeting),
    MASCOT_LINES.new_collection,
    MASCOT_LINES.missing_you,
    MASCOT_LINES.wrote_review,
    ...Object.values(MASCOT_LINES.milestones),
    MASCOT_LINES.fallback,
  ];

  it("主场景各 5-8 句，里程碑各节点有内容", () => {
    for (const t of ["morning", "afternoon", "evening", "night"]) {
      expect(MASCOT_LINES.greeting[t].length).toBeGreaterThanOrEqual(5);
      expect(MASCOT_LINES.greeting[t].length).toBeLessThanOrEqual(8);
    }
    for (const k of ["new_collection", "missing_you", "wrote_review", "fallback"]) {
      expect(MASCOT_LINES[k].length).toBeGreaterThanOrEqual(5);
      expect(MASCOT_LINES[k].length).toBeLessThanOrEqual(8);
    }
    for (const c of MILESTONES.collection) expect(MASCOT_LINES.milestones[`collection:${c}`].length).toBeGreaterThanOrEqual(1);
    for (const r of MILESTONES.review) expect(MASCOT_LINES.milestones[`review:${r}`].length).toBeGreaterThanOrEqual(1);
  });

  it("人设合规：每句都称呼「主人」，句长 ≤40，无客服/数据腔", () => {
    for (const list of allLineLists) {
      for (const line of list) {
        expect(line.length, `句长超限: ${line}`).toBeLessThanOrEqual(40);
        expect(line, `缺「主人」: ${line}`).toContain("主人");
        expect(line, `客服/数据腔: ${line}`).not.toMatch(/已为您|操作成功|共(有|计)|本月新增|如需帮助/);
      }
    }
  });

  it("口癖克制：全库含「喵」的句子不超过一半，且「喵」必带「～」且不连续叠用", () => {
    let meowCount = 0, total = 0;
    for (const list of allLineLists) {
      for (const line of list) {
        total += 1;
        if (line.includes("喵")) {
          meowCount += 1;
          expect(line, `喵形式错误: ${line}`).toMatch(/喵～/);   // 必须是"喵～"
          expect(line, `一句多次喵: ${line}`).not.toMatch(/喵～[^，。！？…]{0,12}喵/); // 不连续叠用
        }
      }
    }
    expect(meowCount / total, "喵～占比过高（要求 ≤ 50%）").toBeLessThanOrEqual(0.5);
  });

  it("想念场景不含抱怨味（有「想/等/念」，无「你才来/忘了」）", () => {
    for (const line of MASCOT_LINES.missing_you) {
      expect(line).not.toMatch(/怎么才来|你才来|你忘了|等得好苦|天荒地老|终于想起/);
    }
  });
});
