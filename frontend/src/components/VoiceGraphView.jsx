// 声优图谱（ADR 0036：从全局图改为"以人为中心"的搜索驱动邻域视图）
// - 默认=搜索入口：搜索框模糊匹配（复用命令面板 matchCommand），默认态展示引导 +
//   配音作品数最多的几位声优快捷入口；
// - 选中声优 → 单声优邻域视图（ego network）：该声优居中 + TA 配过的作品 + 角色 +
//   共同出演的其它声优（外环），规模天然小、放射状布局清晰可读，不再是毛线球；
// - 旧全局图降级为"概览模式"（非默认，需主动进入 + 数据量大提示）。
import React, { useEffect, useMemo, useRef, useState } from "react";
import { fetchVoiceRelations } from "../api.js";
import { TagCapsule } from "./ui.jsx";
import { matchCommand } from "../commands.js";
import {
  LABEL_ACTOR_MIN, VIEW_H, VIEW_W, buildEgo, layoutEgoGraph, layoutGraph,
  pickLabels, shortText,
} from "../voiceLayout.js";

const THRESHOLDS = [2, 3, 5, 8];
const DEFAULT_THRESHOLD = 3;

// Phase 8-2-A：可交互 SVG 节点的键盘激活（Enter / Space → 与鼠标 click 相同业务；
// preventDefault 阻止 Space 滚动页面；键盘不额外触发 click，避免重复执行）。
const activate = (fn) => (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    fn();
  }
};

export default function VoiceGraphView({ focusActor, onOpenWork, className = "" }) {
  const [data, setData] = useState(null);
  const [mode, setMode] = useState("search"); // "search" | "ego" | "overview"
  const [selected, setSelected] = useState(null); // 选中的声优
  const [query, setQuery] = useState("");
  const [threshold, setThreshold] = useState(DEFAULT_THRESHOLD);
  const [loading, setLoading] = useState(true);
  const lastFocus = useRef(null);

  useEffect(() => {
    setLoading(true);
    fetchVoiceRelations()
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  // 角色墙/命令入口传入 focusActor → 直接进入该声优的邻域视图
  useEffect(() => {
    if (focusActor && focusActor !== lastFocus.current && data) {
      lastFocus.current = focusActor;
      const a = data.actors.find((x) => x.name === focusActor);
      if (a) { setSelected(a); setMode("ego"); setQuery(""); }
    }
  }, [focusActor, data]);

  // 搜索过滤（复用命令面板的模糊匹配）
  const searchHits = useMemo(() => {
    if (!data) return [];
    const q = query.trim();
    const hits = (data.actors || []).filter((a) => matchCommand({ title: a.name, keywords: [a.name] }, q));
    hits.sort((a, b) => b.work_count - a.work_count);
    return q ? hits.slice(0, 10) : hits.slice(0, 8); // 空查询 = 快捷入口（作品数最多的几位）
  }, [data, query]);

  // 选中声优的邻域
  const ego = useMemo(() => (selected && data ? buildEgo(selected, data) : null), [selected, data]);
  const egoGraph = useMemo(() => {
    if (!ego) return null;
    layoutEgoGraph(ego);
    // 标签：中心声优强制显示；作品与共同出演声优按连接数优先级 + 碰撞避让
    const candidates = [
      { key: "ego-actor", x: ego.actor.x, y: ego.actor.y, text: shortText(ego.actor.name, 8), priority: 9999 },
    ];
    for (const w of ego.works) {
      candidates.push({ key: "w:" + w.item_id, x: w.x, y: w.y, text: shortText(w.title, 10), priority: w.roles.length });
    }
    for (const c of ego.coActors) {
      candidates.push({ key: "c:" + c.name, x: c.x, y: c.y, text: shortText(c.name, 8), priority: c.shared.length });
    }
    const labelSet = pickLabels(candidates, ["ego-actor"]);
    return { ...ego, labelSet, actorById: new Map(ego.coActors.map((c) => [c.name, c])) };
  }, [ego]);

  // 概览模式的全局图（降级保留，ADR 0036）
  const overview = useMemo(() => {
    if (!data || mode !== "overview") return null;
    const actors = data.actors.filter((a) => a.work_count >= threshold);
    const workIds = new Set();
    for (const a of actors) for (const w of a.works) workIds.add(w.item_id);
    const works = data.works.filter((w) => workIds.has(w.item_id));
    const chars = [];
    for (const a of actors) for (const w of a.works) for (const role of w.roles) {
      chars.push({ actor: a.name, work_id: w.item_id, name: role });
    }
    layoutGraph(works, actors, chars);
    const workConn = new Map();
    for (const a of actors) for (const w of a.works) workConn.set(w.item_id, (workConn.get(w.item_id) || 0) + 1);
    const candidates = [];
    for (const a of actors) {
      if (a.work_count >= LABEL_ACTOR_MIN) {
        candidates.push({ key: "a:" + a.name, x: a.x, y: a.y, text: shortText(a.name, 8), priority: a.work_count });
      }
    }
    for (const w of works) {
      candidates.push({ key: "w:" + w.item_id, x: w.x, y: w.y, text: shortText(w.title, 10), priority: workConn.get(w.item_id) || 1 });
    }
    return { actors, works, chars, labelSet: pickLabels(candidates), actorById: new Map(actors.map((a) => [a.name, a])) };
  }, [data, mode, threshold]);

  if (loading) return <div className={"text-sm " + className} style={{ color: "var(--text-secondary)" }}>加载中…</div>;
  if (!data || (data.actors || []).length === 0) {
    return <div className={"text-sm " + className} style={{ color: "var(--text-secondary)" }}>还没有声优数据（先收藏带角色声优的作品）。</div>;
  }

  const stats = data.stats || {};

  // Phase 8-2-A：声优节点选中复用同一业务函数（鼠标 click 与键盘激活共用）
  const selectActorByName = (name) => {
    const a = data.actors.find((x) => x.name === name);
    if (a) { setSelected(a); setMode("ego"); }
  };

  return (
    <div className={className}>
      {/* 顶部：搜索框 + 概览入口 */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <div className="voice-search-control flex items-center gap-2 px-3.5 py-2 flex-1 min-w-[220px]"
          style={{ backgroundColor: "var(--input-bg)", border: "1px solid var(--input-border)" }}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2"
            className="shrink-0" style={{ color: "var(--text-secondary)" }}>
            <circle cx="11" cy="11" r="7" /><path d="M21 21l-4.35-4.35" />
          </svg>
          <input value={query}
            onChange={(e) => { setQuery(e.target.value); if (mode !== "search") setMode("search"); }}
            placeholder="搜索声优，看 TA 的配音关系网络…"
            className="flex-1 bg-transparent outline-none text-sm min-w-0"
            style={{ color: "var(--text)" }} />
        </div>
        {mode === "ego" && selected && (
          <button type="button" onClick={() => { setSelected(null); setMode("search"); }}
            className="voice-graph-action shrink-0">收起 / 搜索其它声优</button>
        )}
        <button type="button" onClick={() => setMode(mode === "overview" ? "search" : "overview")}
          className={"voice-mode-control shrink-0" + (mode === "overview" ? " voice-mode-control-active" : "")}>
          {mode === "overview" ? "退出全局概览" : "查看全部声优网络"}
        </button>
      </div>

      {mode === "overview" ? (
        /* ---- 概览模式：全局图（降级保留，明确提示数据量大） ---- */
        <>
          <div className="mb-3 text-xs px-4 py-2.5 rounded-2xl"
            style={{ backgroundColor: "rgba(248,113,113,0.12)", color: "var(--text)" }}>
            全局概览：同时渲染 {overview?.actors.length || 0} 位声优 / {overview?.works.length || 0} 部作品，
            数据量大、边密集，可能难以阅读——建议用顶部搜索聚焦单个声优。
          </div>
          <div className="flex items-center gap-2 text-xs mb-2" style={{ color: "var(--text-secondary)" }}>
            <span>最低配音作品数</span>
            {THRESHOLDS.map((t) => (
              <button type="button" key={t} data-threshold={t} onClick={() => setThreshold(t)}
                className={"voice-threshold" + (threshold === t ? " voice-threshold-active" : "")}>
                {t}
              </button>
            ))}
            <span className="ml-1">当前：{overview?.actors.length || 0} 声优 / {overview?.works.length || 0} 作品</span>
          </div>
          <div className="rounded-2xl border overflow-hidden" style={{ backgroundColor: "var(--surface-0)", borderColor: "var(--panel-border)" }}>
            <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} className="w-full" style={{ height: "min(70vh, 640px)" }}
              role="img" aria-label="声优全局概览">
              {overview.chars.map((c, i) => {
                const a = overview.actorById.get(c.actor);
                const w = overview.works.find((x) => x.item_id === c.work_id);
                if (!a || !w) return null;
                return (
                  <g key={i}>
                    <line x1={a.x} y1={a.y} x2={c.x} y2={c.y} stroke="var(--accent)" strokeWidth="1" opacity="0.35" />
                    <line x1={c.x} y1={c.y} x2={w.x} y2={w.y} stroke="var(--panel-border)" strokeWidth="1" opacity="0.35" />
                  </g>
                );
              })}
              {overview.works.map((w) => (
                <g key={w.item_id} onClick={() => onOpenWork?.(w.item_id)} style={{ cursor: "pointer" }}
                  role="button" tabIndex={0} aria-label={w.title}
                  onKeyDown={activate(() => onOpenWork?.(w.item_id))}>
                  <circle cx={w.x} cy={w.y} r="12" fill="var(--surface-2)" stroke="var(--panel-border)" strokeWidth="1">
                    <title>{w.title}</title>
                  </circle>
                  {overview.labelSet.has("w:" + w.item_id) && (
                    <text x={w.x} y={w.y + 26} textAnchor="middle" fontSize="10" fill="var(--text-secondary)"
                      style={{ pointerEvents: "none" }}>{shortText(w.title, 10)}</text>
                  )}
                </g>
              ))}
              {overview.chars.map((c, i) => (
                <circle key={"c" + i} cx={c.x} cy={c.y} r="2.6" fill="var(--tag-bg)" stroke="var(--tag-text)"
                  strokeWidth="1" opacity="0.85" onClick={() => onOpenWork?.(c.work_id)} style={{ cursor: "pointer" }}
                  role="button" tabIndex={0} aria-label={`${c.name}（${c.actor}）`}
                  onKeyDown={activate(() => onOpenWork?.(c.work_id))}>
                  <title>{`${c.name}（${c.actor}）`}</title>
                </circle>
              ))}
              {overview.actors.map((a) => (
                <g key={a.name} onClick={() => selectActorByName(a.name)} style={{ cursor: "pointer" }}
                  role="button" tabIndex={0} aria-label={`声优：${a.name}`}
                  onKeyDown={activate(() => selectActorByName(a.name))}>
                  <circle cx={a.x} cy={a.y} r={Math.min(5 + a.work_count * 0.9, 16)}
                    fill="var(--accent-soft)" stroke="var(--accent)" strokeWidth="1.5">
                    <title>{`${a.name}：配音 ${a.work_count} 部作品`}</title>
                  </circle>
                  {overview.labelSet.has("a:" + a.name) && (
                    <text x={a.x} y={a.y + 24} textAnchor="middle" fontSize="10" fill="var(--text)"
                      style={{ pointerEvents: "none" }}>{shortText(a.name, 8)}</text>
                  )}
                </g>
              ))}
            </svg>
          </div>
        </>
      ) : mode === "ego" && egoGraph ? (
        /* ---- 单声优邻域视图（核心） ---- */
        <div className="rounded-2xl border overflow-hidden" style={{ backgroundColor: "var(--surface-0)", borderColor: "var(--panel-border)" }}>
          <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} className="w-full" style={{ height: "min(70vh, 640px)" }}
            role="img" aria-label="声优邻域关系图">
            {/* 共同出演：外环声优 → 共享作品（细淡线，只表达合作过） */}
            {egoGraph.coActors.map((c) =>
              c.shared.map((wid) => {
                const w = egoGraph.works.find((x) => x.item_id === wid);
                if (!w) return null;
                return <line key={`${c.name}-${wid}`} x1={c.x} y1={c.y} x2={w.x} y2={w.y}
                  stroke="var(--panel-border)" strokeWidth="1" opacity="0.4" />;
              })
            )}
            {/* 选中声优 → 角色 → 作品 */}
            {egoGraph.chars.map((ch, i) => {
              const w = egoGraph.works.find((x) => x.item_id === ch.work_id);
              if (!w) return null;
              return (
                <g key={i}>
                  <line x1={egoGraph.actor.x} y1={egoGraph.actor.y} x2={ch.x} y2={ch.y}
                    stroke="var(--accent)" strokeWidth="1.2" opacity="0.7" />
                  <line x1={ch.x} y1={ch.y} x2={w.x} y2={w.y}
                    stroke="var(--panel-border)" strokeWidth="1" opacity="0.6" />
                </g>
              );
            })}
            {/* 作品节点 */}
            {egoGraph.works.map((w) => (
              <g key={w.item_id} onClick={() => onOpenWork?.(w.item_id)} style={{ cursor: "pointer" }}
                role="button" tabIndex={0} aria-label={w.title}
                onKeyDown={activate(() => onOpenWork?.(w.item_id))}>
                <circle cx={w.x} cy={w.y} r="14" fill="var(--surface-2)" stroke="var(--panel-border)" strokeWidth="1">
                  <title>{w.title}</title>
                </circle>
                {egoGraph.labelSet.has("w:" + w.item_id) && (
                  <text x={w.x} y={w.y + 28} textAnchor="middle" fontSize="10" fill="var(--text-secondary)"
                    style={{ pointerEvents: "none" }}>{shortText(w.title, 10)}</text>
                )}
              </g>
            ))}
            {/* 角色小圆点 */}
            {egoGraph.chars.map((ch, i) => (
              <circle key={"ch" + i} cx={ch.x} cy={ch.y} r="3" fill="var(--tag-bg)" stroke="var(--tag-text)"
                strokeWidth="1" onClick={() => onOpenWork?.(ch.work_id)} style={{ cursor: "pointer" }}
                role="button" tabIndex={0} aria-label={`${ch.name}（${egoGraph.actor.name} 配音）`}
                onKeyDown={activate(() => onOpenWork?.(ch.work_id))}>
                <title>{`${ch.name}（${egoGraph.actor.name} 配音）`}</title>
              </circle>
            ))}
            {/* 共同出演声优（外环） */}
            {egoGraph.coActors.map((c) => (
              <g key={c.name} onClick={() => selectActorByName(c.name)} style={{ cursor: "pointer" }}
                role="button" tabIndex={0} aria-label={`声优：${c.name}`}
                onKeyDown={activate(() => selectActorByName(c.name))}>
                <circle cx={c.x} cy={c.y} r={Math.min(4 + c.shared.length, 11)} fill="var(--accent-soft)"
                  stroke="var(--accent)" strokeWidth="1">
                  <title>{`${c.name}：与 ${egoGraph.actor.name} 共同出演 ${c.shared.length} 部`}</title>
                </circle>
                {egoGraph.labelSet.has("c:" + c.name) && (
                  <text x={c.x} y={c.y + 20} textAnchor="middle" fontSize="9" fill="var(--text)"
                    style={{ pointerEvents: "none" }}>{shortText(c.name, 8)}</text>
                )}
              </g>
            ))}
            {/* 中心声优 */}
            <circle cx={egoGraph.actor.x} cy={egoGraph.actor.y} r="26" fill="var(--accent)" stroke="var(--accent-hover)" strokeWidth="2">
              <title>{`${egoGraph.actor.name}：配音 ${egoGraph.actor.work_count} 部作品`}</title>
            </circle>
            <text x={egoGraph.actor.x} y={egoGraph.actor.y + 42} textAnchor="middle" fontSize="12" fontWeight="600"
              fill="var(--accent)" style={{ pointerEvents: "none" }}>{shortText(egoGraph.actor.name, 10)}</text>
          </svg>
        </div>
      ) : (
        /* ---- 搜索入口 / 引导态（默认） ---- */
        <div>
          <div className="mb-3 text-sm" style={{ color: "var(--text-secondary)" }}>
            搜索一个声优开始探索——查看 TA 配过的作品、角色，以及和 TA 共同出演的其他声优。
          </div>
          {!query.trim() ? (
            <>
              <div className="text-[11px] mb-2 tracking-wider" style={{ color: "var(--text-secondary)" }}>
                配音作品最多的声优（快捷入口）
              </div>
              <div className="flex flex-wrap gap-1.5">
                {searchHits.map((a) => (
                  <button type="button" key={a.name} onClick={() => { setSelected(a); setMode("ego"); }}
                    className="voice-actor-link">
                    {a.name} <span className="opacity-70">· {a.work_count} 部</span>
                  </button>
                ))}
              </div>
            </>
          ) : searchHits.length === 0 ? (
            <div className="text-sm py-8 text-center" style={{ color: "var(--text-secondary)" }}>
              没有匹配「{query}」的声优。
            </div>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {searchHits.map((a) => (
                <button type="button" key={a.name} onClick={() => { setSelected(a); setMode("ego"); }}
                  className="voice-actor-link">
                  {a.name} <span className="opacity-70">· {a.work_count} 部</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
