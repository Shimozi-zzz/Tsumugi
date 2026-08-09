// 声优图谱布局与标签策略（ADR 0035/0036）：标签分级/碰撞避让/布局分散/邻域构建
import { describe, it, expect } from "vitest";
import {
  LABEL_ACTOR_MIN, VIEW_H, VIEW_W, buildEgo, estimateLabel, layoutEgoGraph, layoutGraph, pickLabels,
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

describe("buildEgo（单声优邻域，ADR 0036）", () => {
  const data = {
    works: [
      { item_id: 1, title: "作品甲" }, { item_id: 2, title: "作品乙" }, { item_id: 3, title: "作品丙" },
    ],
    actors: [
      { name: "声优甲", work_count: 2, works: [{ item_id: 1, roles: ["X"] }, { item_id: 2, roles: ["Y"] }] },
      { name: "声优乙", work_count: 2, works: [{ item_id: 1, roles: ["Z"] }, { item_id: 3, roles: ["B"] }] },
      { name: "声优丙", work_count: 2, works: [{ item_id: 1, roles: ["W"] }, { item_id: 3, roles: ["C"] }] },
    ],
  };

  it("只包含选中声优的作品/角色，与共同出演的其它声优", () => {
    const ego = buildEgo(data.actors[0], data);
    expect(ego.works.map((w) => w.item_id)).toEqual([1, 2]); // 不含作品丙
    expect(ego.chars.map((c) => c.name)).toEqual(["X", "Y"]); // 只含声优甲的角色
    const co = ego.coActors.map((c) => c.name).sort();
    expect(co).toEqual(["声优丙", "声优乙"]); // 与作品甲/作品乙共同出演
    // 共同出演声优的 shared 只含共享作品
    const yi = ego.coActors.find((c) => c.name === "声优乙");
    expect(yi.shared).toEqual([1]);
  });

  it("coActorCap 限制共同出演声优数量（避免滚雪球成大图）", () => {
    const ego = buildEgo(data.actors[0], data, { coActorCap: 1 });
    expect(ego.coActors.length).toBe(1);
  });

  it("layoutEgoGraph 放射状：中心=选中声优，作品/共同出演在环上", () => {
    const ego = buildEgo(data.actors[0], data);
    layoutEgoGraph(ego);
    expect(ego.actor.x).toBeCloseTo(VIEW_W / 2);
    expect(ego.actor.y).toBeCloseTo(VIEW_H / 2);
    // 作品在中心附近的内环，共同出演在外环（外环半径更大 → 距中心更远）
    const workDist = Math.hypot(ego.works[0].x - ego.actor.x, ego.works[0].y - ego.actor.y);
    const coDist = Math.hypot(ego.coActors[0].x - ego.actor.x, ego.coActors[0].y - ego.actor.y);
    expect(coDist).toBeGreaterThan(workDist);
  });
});
