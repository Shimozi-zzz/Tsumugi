// 书架/书脊视图：窄条竖排标题 + hover 抽书预览（封面/标题/我的评分）+ 点击进详情
import React, { useRef, useState } from "react";
import { fetchItemDetail } from "../api.js";
import { readCssVar } from "../shareCard.js";
import { spineColor, spineSeed } from "../bookshelf.js";

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
    setHover({ it, x, y, rating: hasRating ? ratings[it.id] : null, loading: !hasRating });
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
  }

  function clearHover() {
    hoverIdRef.current = null;
    setHover(null);
  }

  return (
    <div>
      <div className="flex items-start gap-2.5 overflow-x-auto pb-3"
        style={{ minHeight: 248, scrollbarWidth: "thin" }}>
        {items.map((it) => {
          const color = spineColor(accent, spineSeed(it));
          const selected = selectedIds && selectedIds.has(it.id);
          return (
            <button key={it.id}
              onClick={() => { if (selectMode) onToggleSelect?.(it.id); else onOpenItem(it); }}
              onMouseEnter={(e) => startHover(e, it)}
              onMouseLeave={clearHover}
              onContextMenu={(e) => onContextMenu?.(e, it)}
              title={it.title}
              className="shrink-0 relative overflow-hidden"
              style={{
                width: 36, height: 236, borderRadius: 6,
                backgroundColor: color, cursor: "pointer",
                border: selected ? "2px solid var(--accent)" : "1px solid rgba(255,255,255,0.14)",
                boxShadow: selected ? "0 0 0 2px var(--accent-soft)" : "inset 2px 0 0 rgba(255,255,255,0.16), 0 2px 6px rgba(0,0,0,0.18)",
              }}>
              {selectMode && (
                <span className="absolute top-1 left-1 z-10 w-4 h-4 rounded-full flex items-center justify-center text-[10px]"
                  style={{ backgroundColor: selected ? "var(--accent)" : "rgba(255,255,255,0.9)",
                    color: selected ? "#fff" : "var(--text-secondary)",
                    border: "1px solid var(--accent)" }}>
                  {selected ? "✓" : ""}
                </span>
              )}
              {/* 书脊高光条（左侧） */}
              <span className="absolute left-0 top-0 bottom-0"
                style={{ width: 2, backgroundColor: "rgba(255,255,255,0.20)" }} />
              {/* 竖排标题 */}
              <span className="absolute inset-0 flex items-start justify-center"
                style={{
                  writingMode: "vertical-rl", textOrientation: "mixed",
                  padding: "12px 7px", fontSize: 11, color: "#fff",
                  letterSpacing: 2, lineHeight: 1.35, fontWeight: 500,
                  textAlign: "center", wordBreak: "break-all",
                }}>
                {it.title}
              </span>
              {/* 底部色带（书脊装帧感） */}
              <span className="absolute left-0 right-0 bottom-0"
                style={{ height: 9, backgroundColor: "rgba(0,0,0,0.18)" }} />
            </button>
          );
        })}
        {items.length === 0 && (
          <div className="text-sm py-16" style={{ color: "var(--text-secondary)" }}>
            书架是空的
          </div>
        )}
      </div>

      {/* hover 抽书预览（fixed 定位，脱离滚动） */}
      {hover && (
        <div className="fixed z-40" style={{ left: hover.x, top: hover.y, width: 132, pointerEvents: "none" }}
          data-testid="shelf-preview">
          <div className="rounded-2xl overflow-hidden"
            style={{
              backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)",
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
              <div className="text-xs font-medium leading-snug line-clamp-2"
                style={{ color: "var(--text)" }}>{hover.it.title}</div>
              {hover.loading ? (
                <div className="text-[10px] mt-1" style={{ color: "var(--text-secondary)" }}>评分…</div>
              ) : typeof hover.rating === "number" ? (
                <div className="text-[10px] mt-1" style={{ color: "var(--amber, #ffc24b)" }}>
                  我的评分 ★{hover.rating}
                </div>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
