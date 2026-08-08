// 声优图谱（ADR 0032）：作品-角色-声优 关系网络（轻量 SVG，自绘确定性布局）
// - 布局：作品环绕外圈，声优放在其配音作品的质心 + 重叠松弛（力导向的确定性近似，
//   一次算完，无实时 O(n²) 帧循环；角色节点置于声优→作品连线的中点偏移）；
// - 节点：声优=accent 圆（越大配音作品越多）、作品=surface-2 圆、角色=小圆点；
// - 交互：点声优 → 下方展示完整配音列表并高亮子图；点作品/角色 → 复用主从视图跳详情；
// - 视觉走 token，不引入独立配色；默认阈值"配音作品数≥2"（剔除 663 个只配一作的孤立
//   声优，见 ADR 0032 实测数据），提供 2/3/5/8 调节。
import React, { useEffect, useMemo, useState } from "react";
import { fetchVoiceRelations } from "../api.js";
import { TagCapsule } from "./ui.jsx";

const THRESHOLDS = [2, 3, 5, 8];
const VIEW_W = 960;
const VIEW_H = 700;

// 确定性布局：works 圆形环绕；actors 放置到其作品质心 + 重叠松弛；
// characters 在 声优→作品 线段中点垂直偏移（避免多角色重叠）。
function layoutGraph(works, actors, chars) {
  const cx = VIEW_W / 2, cy = VIEW_H / 2;
  const R = Math.min(VIEW_W, VIEW_H) / 2 - 70;
  const workById = new Map(works.map((w) => [w.item_id, w]));
  works.forEach((w, i) => {
    const ang = (2 * Math.PI * i) / Math.max(works.length, 1) - Math.PI / 2;
    w.x = cx + R * Math.cos(ang);
    w.y = cy + R * Math.sin(ang);
  });
  actors.forEach((a) => {
    const ids = a.works.map((w) => w.item_id);
    if (!ids.length) { a.x = cx; a.y = cy; return; }
    let sx = 0, sy = 0;
    for (const id of ids) { const w = workById.get(id); if (w) { sx += w.x; sy += w.y; } }
    a.x = sx / ids.length;
    a.y = sy / ids.length;
  });
  for (let iter = 0; iter < 70; iter++) {
    for (const a of actors) {
      const ids = a.works.map((w) => w.item_id);
      let fx = 0, fy = 0;
      // 拉回自身作品质心
      let cx0 = 0, cy0 = 0, n = 0;
      for (const id of ids) { const w = workById.get(id); if (w) { cx0 += w.x; cy0 += w.y; n++; } }
      if (n) { fx += (cx0 / n - a.x) * 0.04; fy += (cy0 / n - a.y) * 0.04; }
      // 声优间排斥（防重叠）
      for (const b of actors) {
        if (b === a) continue;
        const dx = a.x - b.x, dy = a.y - b.y, d = Math.hypot(dx, dy) || 1e-6;
        if (d < 55) { const f = (55 - d) * 0.012; fx += (dx / d) * f; fy += (dy / d) * f; }
      }
      // 与作品排斥（防贴边）
      for (const w of works) {
        const dx = a.x - w.x, dy = a.y - w.y, d = Math.hypot(dx, dy) || 1e-6;
        if (d < 60) { const f = (60 - d) * 0.008; fx += (dx / d) * f; fy += (dy / d) * f; }
      }
      a.x += Math.max(-10, Math.min(10, fx));
      a.y += Math.max(-10, Math.min(10, fy));
    }
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

export default function VoiceGraphView({ focusActor, onOpenWork, className = "" }) {
  const [data, setData] = useState(null);
  const [threshold, setThreshold] = useState(2);
  const [selected, setSelected] = useState(null); // 选中的声优
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchVoiceRelations()
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  // 外部传入 focusActor（角色墙/命令面板入口）→ 自动选中
  useEffect(() => {
    if (focusActor && data) {
      const a = data.actors.find((x) => x.name === focusActor);
      if (a) setSelected(a);
    }
  }, [focusActor, data]);

  const graph = useMemo(() => {
    if (!data) return null;
    const actors = data.actors.filter((a) => a.work_count >= threshold);
    const workIds = new Set();
    for (const a of actors) for (const w of a.works) workIds.add(w.item_id);
    const works = data.works.filter((w) => workIds.has(w.item_id));
    const chars = [];
    for (const a of actors) for (const w of a.works) for (const role of w.roles) {
      chars.push({ actor: a.name, work_id: w.item_id, name: role });
    }
    const node = { actors, works, chars };
    layoutGraph(node.works, node.actors, node.chars);
    // 选中声优高亮：仅保留其连通的节点可见
    const selectedSet = selected ? new Set(selected.works.map((w) => w.item_id)) : null;
    node.actorVisible = (a) => !selectedSet || a.name === selected.name;
    node.workVisible = (w) => !selectedSet || selectedSet.has(w.item_id) || selected.works.some((x) => x.item_id === w.item_id);
    node.charVisible = (c) => !selectedSet || (c.actor === selected.name && selectedSet.has(c.work_id));
    return node;
  }, [data, threshold, selected]);

  if (loading) return <div className={"text-sm " + className} style={{ color: "var(--text-secondary)" }}>加载中…</div>;
  if (!data || !graph || data.actors.length === 0) {
    return <div className={"text-sm " + className} style={{ color: "var(--text-secondary)" }}>还没有声优数据（先收藏带角色声优的作品）。</div>;
  }

  const stats = data.stats || {};
  const actorById = new Map(graph.actors.map((a) => [a.name, a]));

  return (
    <div className={className}>
      {/* 顶部：阈值控制 + 统计 */}
      <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
        <div className="flex items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
          <span>最低配音作品数</span>
          {THRESHOLDS.map((t) => (
            <button key={t} data-threshold={t} onClick={() => setThreshold(t)}
              className="px-2 py-1 rounded-lg text-[11px]"
              style={{ backgroundColor: threshold === t ? "var(--accent)" : "var(--surface-2)",
                color: threshold === t ? "#fff" : "var(--text)" }}>
              {t}
            </button>
          ))}
          <span className="ml-1">当前：{graph.actors.length} 声优 / {graph.works.length} 作品</span>
        </div>
        {stats.missing_actor_chars > 0 && (
          <span className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
            共 {stats.actor_count} 位声优；{stats.missing_actor_chars} 个角色暂无声优数据（未入图）
          </span>
        )}
      </div>

      {/* SVG 图谱 */}
      <div className="rounded-2xl border overflow-hidden" style={{ backgroundColor: "var(--surface-0)", borderColor: "var(--panel-border)" }}>
        <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} className="w-full" style={{ height: "min(70vh, 640px)" }}
          role="img" aria-label="声优关系图谱">
          {/* 边：声优→角色 + 角色→作品 连成一条 */}
          {graph.chars.map((c, i) => {
            const a = actorById.get(c.actor);
            const w = graph.works.find((x) => x.item_id === c.work_id);
            if (!a || !w || !graph.charVisible(c)) return null;
            const opacity = selected && c.actor === selected.name ? 0.85 : 0.35;
            return (
              <g key={i}>
                <line x1={a.x} y1={a.y} x2={c.x} y2={c.y} stroke="var(--accent)" strokeWidth="1" opacity={opacity} />
                <line x1={c.x} y1={c.y} x2={w.x} y2={w.y} stroke="var(--panel-border)" strokeWidth="1" opacity={opacity} />
              </g>
            );
          })}
          {/* 作品节点 */}
          {graph.works.map((w) => (
            graph.workVisible(w) && (
              <g key={w.item_id} onClick={() => onOpenWork?.(w.item_id)}
                style={{ cursor: "pointer" }}>
                <circle cx={w.x} cy={w.y} r="12" fill="var(--surface-2)" stroke="var(--panel-border)" strokeWidth="1" />
                <text x={w.x} y={w.y + 26} textAnchor="middle" fontSize="10" fill="var(--text-secondary)"
                  style={{ pointerEvents: "none" }}>
                  {w.title.length > 10 ? w.title.slice(0, 10) + "…" : w.title}
                </text>
              </g>
            )
          ))}
          {/* 角色节点 */}
          {graph.chars.map((c, i) => (
            graph.charVisible(c) && (
              <circle key={"c" + i} cx={c.x} cy={c.y} r="3.2" fill="var(--tag-bg)" stroke="var(--tag-text)"
                strokeWidth="1" onClick={() => onOpenWork?.(c.work_id)} style={{ cursor: "pointer" }}>
                <title>{`${c.name}（${c.actor}）`}</title>
              </circle>
            )
          ))}
          {/* 声优节点 */}
          {graph.actors.map((a) => (
            graph.actorVisible(a) && (
              <g key={a.name} onClick={() => setSelected(selected && selected.name === a.name ? null : a)}
                style={{ cursor: "pointer" }}>
                <circle cx={a.x} cy={a.y} r={Math.min(6 + a.work_count * 1.1, 18)}
                  fill={selected && selected.name === a.name ? "var(--accent)" : "var(--accent-soft)"}
                  stroke="var(--accent)" strokeWidth="1.5" />
                <text x={a.x} y={a.y + 24} textAnchor="middle" fontSize="10"
                  fill={selected && selected.name === a.name ? "var(--accent)" : "var(--text)"}
                  style={{ pointerEvents: "none" }}>
                  {a.name.length > 8 ? a.name.slice(0, 8) + "…" : a.name}
                </text>
              </g>
            )
          ))}
        </svg>
      </div>

      {/* 选中的声优详情：完整配音列表 */}
      {selected && (
        <div className="mt-4 rounded-2xl p-4" style={{ backgroundColor: "var(--surface-1)", border: "1px solid var(--panel-border)" }}>
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            <TagCapsule text={selected.name} />
            <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
              配音 {selected.work_count} 部作品 · {selected.role_count} 个角色
            </span>
            <button onClick={() => setSelected(null)} className="ml-auto text-[11px]" style={{ color: "var(--text-secondary)" }}>收起</button>
          </div>
          <div className="space-y-2">
            {selected.works.map((w) => (
              <div key={w.item_id} className="flex items-center gap-2 text-sm">
                <button onClick={() => onOpenWork?.(w.item_id)}
                  className="max-w-[220px] truncate hover:underline" style={{ color: "var(--accent)" }}>
                  {w.title}
                </button>
                <span className="text-[11px] flex-1 flex flex-wrap gap-1" style={{ color: "var(--text-secondary)" }}>
                  {w.roles.map((r) => <span key={r}>「{r}」</span>)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
