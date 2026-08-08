// 声优图谱（ADR 0032 + 0035 可读性修复）：
// - 布局：voiceLayout.layoutGraph（作品绕圈 + 声优质心 + 强重叠松弛，160 轮 +
//   最小间距 74，避免中心挤压成实心团块）；
// - 标签分级（ADR 0035）：只有高连接声优（配音作品数≥LABEL_ACTOR_MIN）与作品才
//   显示文字标签，且做**碰撞避让**（重叠时隐藏优先级低的）；其余节点只显示圆点，
//   hover 显示名称（<title>）。高密度下仍可读。
import React, { useEffect, useMemo, useState } from "react";
import { fetchVoiceRelations } from "../api.js";
import { TagCapsule } from "./ui.jsx";
import {
  LABEL_ACTOR_MIN, VIEW_H, VIEW_W, layoutGraph, pickLabels, shortText,
} from "../voiceLayout.js";

const THRESHOLDS = [2, 3, 5, 8];
// 默认阈值：实测 ≥2 为 357 声优（挤压成实心），≥3 为 159 声优、≥5 为 41 声优。
// 默认取 3（保留较完整的跨作品网络，配合标签分级/碰撞后仍可读），见 ADR 0035。
const DEFAULT_THRESHOLD = 3;

export default function VoiceGraphView({ focusActor, onOpenWork, className = "" }) {
  const [data, setData] = useState(null);
  const [threshold, setThreshold] = useState(DEFAULT_THRESHOLD);
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
    layoutGraph(works, actors, chars);

    // 作品连接数（用于作品标签优先级）
    const workConn = new Map();
    for (const a of actors) for (const w of a.works) {
      workConn.set(w.item_id, (workConn.get(w.item_id) || 0) + 1);
    }
    // 标签候选：高连接声优 + 全部作品；碰撞避让后只保留放得下且不重叠的
    const candidates = [];
    for (const a of actors) {
      if (a.work_count >= LABEL_ACTOR_MIN) {
        candidates.push({
          key: "a:" + a.name, x: a.x, y: a.y,
          text: shortText(a.name, 8), priority: a.work_count,
        });
      }
    }
    for (const w of works) {
      candidates.push({
        key: "w:" + w.item_id, x: w.x, y: w.y,
        text: shortText(w.title, 10), priority: workConn.get(w.item_id) || 1,
      });
    }
    const forcedKeys = selected ? ["a:" + selected.name] : [];
    const labelSet = pickLabels(candidates, forcedKeys);

    // 选中声优高亮：仅保留其连通的节点可见
    const selectedSet = selected ? new Set(selected.works.map((w) => w.item_id)) : null;
    return {
      actors, works, chars, labelSet,
      actorVisible: (a) => !selectedSet || a.name === selected.name,
      workVisible: (w) => !selectedSet || selectedSet.has(w.item_id) || selected.works.some((x) => x.item_id === w.item_id),
      charVisible: (c) => !selectedSet || (c.actor === selected.name && selectedSet.has(c.work_id)),
    };
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
                <circle cx={w.x} cy={w.y} r="12" fill="var(--surface-2)" stroke="var(--panel-border)" strokeWidth="1">
                  <title>{w.title}</title>
                </circle>
                {graph.labelSet.has("w:" + w.item_id) && (
                  <text x={w.x} y={w.y + 26} textAnchor="middle" fontSize="10" fill="var(--text-secondary)"
                    style={{ pointerEvents: "none" }}>
                    {shortText(w.title, 10)}
                  </text>
                )}
              </g>
            )
          ))}
          {/* 角色节点（小圆点 + hover 名称，不占文字标签） */}
          {graph.chars.map((c, i) => (
            graph.charVisible(c) && (
              <circle key={"c" + i} cx={c.x} cy={c.y} r="2.6" fill="var(--tag-bg)" stroke="var(--tag-text)"
                strokeWidth="1" opacity="0.85" onClick={() => onOpenWork?.(c.work_id)}
                style={{ cursor: "pointer" }}>
                <title>{`${c.name}（${c.actor}）`}</title>
              </circle>
            )
          ))}
          {/* 声优节点 */}
          {graph.actors.map((a) => (
            graph.actorVisible(a) && (
              <g key={a.name} onClick={() => setSelected(selected && selected.name === a.name ? null : a)}
                style={{ cursor: "pointer" }}>
                <circle cx={a.x} cy={a.y} r={Math.min(5 + a.work_count * 0.9, 16)}
                  fill={selected && selected.name === a.name ? "var(--accent)" : "var(--accent-soft)"}
                  stroke="var(--accent)" strokeWidth="1.5">
                  <title>{`${a.name}：配音 ${a.work_count} 部作品`}</title>
                </circle>
                {graph.labelSet.has("a:" + a.name) && (
                  <text x={a.x} y={a.y + 24} textAnchor="middle" fontSize="10"
                    fill={selected && selected.name === a.name ? "var(--accent)" : "var(--text)"}
                    style={{ pointerEvents: "none" }}>
                    {shortText(a.name, 8)}
                  </text>
                )}
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
