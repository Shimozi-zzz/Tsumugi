// 真书架（P5 / ADR 0049）：层板线 + 按主标签分架 + 书脊厚度来自数据 + hover 取书浮起
// 对 ADR 0019"书脊列表"的有意推翻（详见 ADR 0049）；书脊配色仍按标签哈希（0019），
// 但书架有了"空间"：每层一个分类标签 + 层板线，书站上去、hover 浮起、点击进详情。
// hover 抽书预览（封面/标题/我的评分）保留。
import React, { useRef, useState } from "react";
import { fetchItemDetail, fetchItemReviews } from "../api.js";
import { readCssVar } from "../shareCard.js";
import { spineColor, spineSeed, spineThickness, groupBookshelf } from "../bookshelf.js";
import CoverAmbient from "./CoverAmbient.jsx";

export default function Bookshelf({ items, coverOf, onOpenItem, selectMode, selectedIds, onToggleSelect, onContextMenu }) {
  const [hover, setHover] = useState(null); // {it, x, y, rating, loading}
  const [ratings, setRatings] = useState({}); // item_id -> my_rating
  const hoverIdRef = useRef(null);

  const accent = readCssVar("--accent", "#f09199");

  async function startHover(e, it) {
    const rect = e.currentTarget.getBoundingClientRect();
    hoverIdRef.current = it.id;
    const vw = window.innerWidth || 1024;
    const x = Math.min(rect.right + 10, vw - 160);
    const y = Math.max(rect.top - 30, 8);
    const hasRating = it.id in ratings;
    setHover({ it, x, y, rating: hasRating ? ratings[it.id] : null, loading: !hasRating, snippet: "" });
    if (!hasRating) {
      try {
        const d = await fetchItemDetail(it.id);
        setRatings((prev) => ({ ...prev, [it.id]: d.my_rating }));
        if (hoverIdRef.current === it.id) {
          setHover((h) => (h ? { ...h, rating: d.my_rating, loading: false } : h));
        }
      } catch {
        if (hoverIdRef.current === it.id) {
          setHover((h) => (h ? { ...h, loading: false } : h));
        }
      }
    }
    // 书评摘录（索书卡上的"借阅记录"式片段）：最新一条非剧透书评内容首行
    try {
      const reviews = await fetchItemReviews(it.id);
      if (hoverIdRef.current !== it.id) return;
      const r = (reviews || []).find((x) => !x.spoiler && (x.content || "").trim());
      const text = (r?.content || "").replace(/\s+/g, " ").trim();
      setHover((h) => (h ? { ...h, snippet: text.slice(0, 56) + (text.length > 56 ? "…" : "") } : h));
    } catch { /* 无书评则不出片段 */ }
  }

  function clearHover() {
    hoverIdRef.current = null;
    setHover(null);
  }

  const groups = groupBookshelf(items);

  return (
    <div>
      {groups.map((g) => (
        <div key={g.tag} className="mb-6" data-testid="shelf-group">
          {/* 分类架标签（左侧边目录卡标签） */}
          <div className="shelf-label" data-testid="shelf-label">
            <span className="shelf-label-tag">{g.tag}</span>
            <span className="shelf-label-count">{g.items.length} 册</span>
          </div>
          {/* 一层书（站在层板上） */}
          <div className="flex items-end gap-1.5 px-1 overflow-x-auto"
            style={{ minHeight: 216, scrollbarWidth: "thin" }}>
            {g.items.map((it) => {
              const color = spineColor(accent, spineSeed(it));
              const selected = selectedIds && selectedIds.has(it.id);
              return (
                <CoverAmbient key={it.id} src={coverOf(it)} radius={6} blur={12} spread={1} alphaFactor={0.7}>
                <button
                  onClick={() => { if (selectMode) onToggleSelect?.(it.id); else onOpenItem(it); }}
                  onMouseEnter={(e) => startHover(e, it)}
                  onMouseLeave={clearHover}
                  onContextMenu={(e) => onContextMenu?.(e, it)}
                  title={it.title}
                  className="shelf-book shrink-0 relative overflow-hidden"
                  style={{
                    width: spineThickness(it), height: 210, borderRadius: 4,
                    backgroundColor: color, cursor: "pointer",
                    border: selected ? "2px solid var(--accent)" : "1px solid rgba(80,60,35,0.18)",
                    boxShadow: selected ? "0 0 0 2px var(--accent-soft)" : "inset 2px 0 0 rgba(255,255,255,0.35), 0 2px 5px rgba(80,60,35,0.14)",
                  }}>
                  {selectMode && (
                    <span className="absolute top-1 left-1 z-10 w-4 h-4 rounded-full flex items-center justify-center text-[10px]"
                      style={{ backgroundColor: selected ? "var(--accent)" : "rgba(255,255,255,0.9)",
                        color: selected ? "#fff" : "var(--text-secondary)",
                        border: "1px solid var(--accent)" }}>
                      {selected ? "✓" : ""}
                    </span>
                  )}
                  <span className="absolute left-0 top-0 bottom-0"
                    style={{ width: 2, backgroundColor: "rgba(255,255,255,0.45)" }} />
                  <span className="absolute inset-0 flex items-start justify-center"
                    style={{
                      writingMode: "vertical-rl", textOrientation: "mixed",
                      padding: "12px 6px", fontSize: 11, color: "var(--text)",
                      letterSpacing: 2, lineHeight: 1.35, fontWeight: 600,
                      textAlign: "center", wordBreak: "break-all",
                    }}>
                    {it.title}
                  </span>
                  <span className="absolute left-0 right-0 bottom-0"
                    style={{ height: 9, backgroundColor: "rgba(80,60,35,0.22)" }} />
                </button>
                </CoverAmbient>
              );
            })}
          </div>
          {/* 层板线（书架板，书站在上面） */}
          <div className="shelf-board mx-1 mt-0.5"
            style={{
              height: 7, borderRadius: 3,
              background: "linear-gradient(180deg, var(--surface-1), var(--surface-2))",
              borderBottom: "1px solid var(--panel-border)",
              boxShadow: "0 2px 3px rgba(0,0,0,0.10)",
            }} />
        </div>
      ))}
      {items.length === 0 && (
        <div className="text-sm py-16" style={{ color: "var(--text-secondary)" }}>
          书架是空的
        </div>
      )}

      {/* hover 抽书预览（fixed 定位，脱离滚动） */}
      {hover && (
        <div className="fixed z-40" style={{ left: hover.x, top: hover.y, width: 132, pointerEvents: "none" }}
          data-testid="shelf-preview">
          <div className="overflow-hidden"
            style={{
              backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)",
              borderRadius: "var(--radius-floating)",
              boxShadow: "0 14px 34px rgba(0,0,0,0.34)",
            }}>
            {coverOf(hover.it) ? (
              <img src={coverOf(hover.it)} alt="" className="w-full object-cover"
                style={{ aspectRatio: "3/4", background: "var(--card-thumb)" }}
                onError={(e) => { e.target.style.display = "none"; }} />
            ) : (
              <div className="w-full flex items-center justify-center text-2xl"
                style={{ aspectRatio: "3/4", background: "var(--card-thumb)", color: "var(--accent)" }}>
                {(hover.it.title || "?").slice(0, 1)}
              </div>
            )}
            <div className="p-2">
              <div className="catalog-no mb-0.5">NO. {String(hover.it.id != null ? hover.it.id : 0).padStart(4, "0")}</div>
              <div className="text-xs font-medium leading-snug line-clamp-2"
                style={{ color: "var(--text)" }}>{hover.it.title}</div>
              {hover.loading ? (
                <div className="text-[10px] mt-1" style={{ color: "var(--text-secondary)" }}>评分…</div>
              ) : typeof hover.rating === "number" ? (
                <div className="text-[10px] mt-1" style={{ color: "var(--amber, #ffc24b)" }}>
                  我的评分 ★{hover.rating}
                </div>
              ) : null}
              {hover.snippet && (
                <div className="text-[10px] leading-snug mt-1 italic" style={{ color: "var(--text-secondary)" }}>
                  「{hover.snippet}」
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
