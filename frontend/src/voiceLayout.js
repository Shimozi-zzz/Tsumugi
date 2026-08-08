// 声优图谱布局与标签策略（ADR 0035：修复默认视图可读性）
// 纯函数模块，便于单元测试。布局：作品绕圈 + 声优质心 + 强重叠松弛（更多轮数 +
// 更大最小间距，避免中心挤压成团）；标签：高连接节点才有文字标签 + 碰撞避让，
// 其余节点只显示圆点 + hover tooltip。

export const VIEW_W = 960;
export const VIEW_H = 700;
// 声优文字标签的最低连接数：配音作品数 ≥ 此值才进入标签候选（碰撞后仍可能被隐藏）
export const LABEL_ACTOR_MIN = 4;

/**
 * 确定性布局：works 圆形环绕；actors 放到其配音作品质心，再跑强重叠松弛；
 * characters 置于 声优→作品 线段中点垂直偏移。
 * 相比旧版：迭代 70→160、最小间距 55→74、排斥力增强，防止高密度下中心挤压成实心。
 */
export function layoutGraph(works, actors, chars) {
  const cx = VIEW_W / 2, cy = VIEW_H / 2;
  const R = Math.min(VIEW_W, VIEW_H) / 2 - 70;
  const workById = new Map(works.map((w) => [w.item_id, w]));
  works.forEach((w, i) => {
    const ang = (2 * Math.PI * i) / Math.max(works.length, 1) - Math.PI / 2;
    w.x = cx + R * Math.cos(ang);
    w.y = cy + R * Math.sin(ang);
  });
  actors.forEach((a, idx) => {
    const ids = a.works.map((w) => w.item_id);
    let sx = 0, sy = 0, n = 0;
    for (const id of ids) { const w = workById.get(id); if (w) { sx += w.x; sy += w.y; n++; } }
    // 确定性抖动：打破对称坍缩——若多个声优全部落在同一质心，彼此斥力向量会抵消
    // 而原地不动；加一个随索引变化的初始偏移即可让斥力推动它们散开。
    const jitter = 6 + ((idx * 37) % 26);
    a.x = (n ? sx / n : cx) + Math.cos(idx * 2.399) * jitter;
    a.y = (n ? sy / n : cy) + Math.sin(idx * 2.399) * jitter;
  });
  const MIN_D = 74;   // 节点间最小间距（旧 55）
  const ITER = 160;   // 松弛轮数（旧 70）
  for (let iter = 0; iter < ITER; iter++) {
    for (const a of actors) {
      const ids = a.works.map((w) => w.item_id);
      let fx = 0, fy = 0;
      // 拉回自身作品质心
      let cx0 = 0, cy0 = 0, n = 0;
      for (const id of ids) { const w = workById.get(id); if (w) { cx0 += w.x; cy0 += w.y; n++; } }
      if (n) { fx += (cx0 / n - a.x) * 0.05; fy += (cy0 / n - a.y) * 0.05; }
      // 声优间强排斥（防中心挤压成团）
      for (const b of actors) {
        if (b === a) continue;
        const dx = a.x - b.x, dy = a.y - b.y, d = Math.hypot(dx, dy) || 1e-6;
        if (d < MIN_D) { const f = (MIN_D - d) * 0.02; fx += (dx / d) * f; fy += (dy / d) * f; }
      }
      // 与作品排斥（防贴边）
      for (const w of works) {
        const dx = a.x - w.x, dy = a.y - w.y, d = Math.hypot(dx, dy) || 1e-6;
        if (d < MIN_D) { const f = (MIN_D - d) * 0.012; fx += (dx / d) * f; fy += (dy / d) * f; }
      }
      a.x += Math.max(-12, Math.min(12, fx));
      a.y += Math.max(-12, Math.min(12, fy));
    }
  }
  // 钳制在画布内（留边距给文字标签）
  for (const a of actors) {
    a.x = Math.max(40, Math.min(VIEW_W - 40, a.x));
    a.y = Math.max(40, Math.min(VIEW_H - 40, a.y));
  }
  let ci = 0;
  chars.forEach((c) => {
    const a = actors.find((x) => x.name === c.actor);
    const w = workById.get(c.work_id);
    if (!a || !w) { c.x = cx; c.y = cy; return; }
    const mx = (a.x + w.x) / 2, my = (a.y + w.y) / 2;
    const dx = w.x - a.x, dy = w.y - a.y, len = Math.hypot(dx, dy) || 1;
    const off = (ci % 2 ? 1 : -1) * 5 * ((ci >> 1) % 3 + 1);
    c.x = mx + (-dy / len) * off;
    c.y = my + (dx / len) * off;
    ci++;
  });
}

/** 估算文字标签的包围盒（用于碰撞检测）。text 以 (x, y+24) 为锚点居中。
 * 宽度系数取 0.9（中文为全角 ≈1em，混合场景保守估宽），避免估算过窄导致
 * 实际渲染仍重叠。 */
export function estimateLabel(x, y, text, fontSize = 10) {
  const w = text.length * fontSize * 0.9 + 10;
  const h = fontSize + 4;
  return { x0: x - w / 2, x1: x + w / 2, y0: y + 22, y1: y + 22 + h };
}

/**
 * 标签碰撞避让：按优先级降序贪心放置，与已接受标签重叠则隐藏（优先级低的让位）。
 * candidates: [{key, x, y, text, priority}]；forcedKeys: 强制显示（如选中的声优）。
 * 返回 {key: true} 的 Set（显示文字标签的节点）。
 */
export function pickLabels(candidates, forcedKeys = []) {
  const forcedSet = new Set(forcedKeys);
  const accepted = [];
  const sorted = [...candidates].sort((a, b) => {
    if (forcedSet.has(a.key) !== forcedSet.has(b.key)) return forcedSet.has(a.key) ? -1 : 1;
    return (b.priority - a.priority) || (a.text.length - b.text.length);
  });
  for (const c of sorted) {
    const box = estimateLabel(c.x, c.y, c.text);
    const hit = accepted.some((a) => !(a.x1 < box.x0 || a.x0 > box.x1 || a.y1 < box.y0 || a.y0 > box.y1));
    if (forcedSet.has(c.key) || !hit) {
      accepted.push({ ...box, key: c.key });
    }
  }
  return new Set(accepted.map((a) => a.key));
}

/** 截断文本。 */
export function shortText(s, max) {
  return s.length > max ? s.slice(0, max) + "…" : s;
}
