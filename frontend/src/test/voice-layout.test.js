// 声优图谱布局与标签策略（ADR 0035）：标签分级/碰撞避让/布局分散
import { describe, it, expect } from "vitest";
import {
  LABEL_ACTOR_MIN, VIEW_H, VIEW_W, estimateLabel, layoutGraph, pickLabels,
} from "../voiceLayout.js";

describe("pickLabels（标签碰撞避让）", () => {
  it("不重叠 → 全部显示", () => {
    const set = pickLabels([
      { key: "a", x: 100, y: 100, text: "AAAA", priority: 5 },
      { key: "b", x: 400, y: 100, text: "BBBB", priority: 3 },
    ]);
    expect(set.has("a")).toBe(true);
    expect(set.has("b")).toBe(true);
  });

  it("重叠 → 隐藏优先级低的那一个（高连接优先显示）", () => {
    const set = pickLabels([
      { key: "low", x: 200, y: 100, text: "LOW", priority: 2 },
      { key: "high", x: 210, y: 100, text: "HIGH", priority: 8 },
    ]);
    expect(set.has("high")).toBe(true);
    expect(set.has("low")).toBe(false);
  });

  it("forcedKeys 强制显示（即使与高优先级重叠也保留）", () => {
    const set = pickLabels([
      { key: "x", x: 200, y: 100, text: "X", priority: 1 },
      { key: "y", x: 205, y: 100, text: "Y", priority: 5 },
    ], ["x"]);
    expect(set.has("x")).toBe(true);   // 选中声优的标签强制显示
    expect(set.has("y")).toBe(false);  // y 与 x 重叠被避让
  });
});

describe("estimateLabel（包围盒估算）", () => {
  it("宽度随文字长度增长", () => {
    const a = estimateLabel(100, 100, "AB");
    const b = estimateLabel(100, 100, "ABCDEFGHIJ");
    expect(b.x1 - b.x0).toBeGreaterThan(a.x1 - a.x0);
  });
});

describe("layoutGraph（布局分散）", () => {
  it("所有节点坐标都在画布内（钳制生效）", () => {
    const works = [{ item_id: 1 }, { item_id: 2 }, { item_id: 3 }];
    const actors = [
      { name: "a", works: [{ item_id: 1 }, { item_id: 2 }] },
      { name: "b", works: [{ item_id: 2 }, { item_id: 3 }] },
    ];
    const chars = [{ actor: "a", work_id: 1 }, { actor: "b", work_id: 3 }];
    layoutGraph(works, actors, chars);
    for (const n of [...works, ...actors, ...chars]) {
      expect(n.x).toBeGreaterThanOrEqual(0);
      expect(n.x).toBeLessThanOrEqual(VIEW_W);
      expect(n.y).toBeGreaterThanOrEqual(0);
      expect(n.y).toBeLessThanOrEqual(VIEW_H);
    }
  });

  it("多个声优共享一个作品时被强排斥拉开（不再堆成一点）", () => {
    const works = [{ item_id: 1 }];
    const actors = Array.from({ length: 8 }, (_, i) => ({ name: "a" + i, works: [{ item_id: 1 }] }));
    layoutGraph(works, actors, []);
    const xs = actors.map((a) => a.x);
    const spread = Math.max(...xs) - Math.min(...xs);
    expect(spread).toBeGreaterThan(50); // 明显分散成环（非全部挤在同一点）；单个作品锚点时
    // 受质心引力约束，不会无限拉开——"不堆成一点"是目标
  });

  it("LABEL_ACTOR_MIN 默认 >= 4（只给高连接声优文字标签）", () => {
    expect(LABEL_ACTOR_MIN).toBeGreaterThanOrEqual(4);
  });
});
