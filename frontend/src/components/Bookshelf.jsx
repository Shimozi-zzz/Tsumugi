// 真书架（P5 / ADR 0049；Phase 7-2 / ADR 0078 视觉结构重做）
// 数据逻辑冻结：spineColor / spineSeed / spineThickness / groupBookshelf 全保留。
// 视觉重做：
//  - 每个分类 = 一个「书架单元」：分类索引（serif + mono 册数 + hairline）+ 书架匣 + 层板
//  - 书 = 实体馆藏对象：数据厚度映射到 15..45px（读得出厚薄），圆柱明暗 + 头带/底脚 + 接触影
//  - hover = 抽书（轻微上浮 + 环境光，保留 CoverAmbient / 评分 / 书评摘录）
//  - 移动端书脊最小 24px，杜绝不可用的细柱
//  - 交互保留：点击进详情 / selectMode / 右键菜单 / hover 预览
import React, { useRef, useState } from "react";
import { fetchItemDetail, fetchItemReviews } from "../api.js";
import { readCssVar } from "../shareCard.js";
import { spineColor, spineSeed, spineThickness, groupBookshelf } from "../bookshelf.js";
import CoverAmbient from "./CoverAmbient.jsx";

// 数据驱动厚度（9..28）→ 可视书脊宽度（22..46px）：保留 spineThickness 的相对关系，
// 映射到能让"书"读出厚薄、且书名可读的屏幕尺度（常规书 22-25px，厚书近 46px）。
function bookWidth(it) {
  const t = spineThickness(it);
  return Math.round(22 + ((t - 9) / 19) * 24);
}

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
    <div className="shelf-view">
      {groups.map((g) => (
        <div key={g.tag} className="shelf-unit" data-testid="shelf-group">
          {/* 分类索引：serif 分类名 + mono 册数 + hairline 延伸线（比书安静） */}
          <div className="shelf-index" data-testid="shelf-label">
            <span className="shelf-index-name">{g.tag}</span>
            <span className="shelf-index-count">{g.items.length} 册</span>
            <span className="shelf-index-rule" aria-hidden />
          </div>
          {/* 书架匣：一格书架（hairline 围合 + 顶部微光），书站在层板上 */}
          <div className="shelf-case">
            <div className="shelf-books">
              {g.items.map((it) => {
                const color = spineColor(accent, spineSeed(it));
                const selected = selectedIds && selectedIds.has(it.id);
                const w = bookWidth(it);
                return (
                  <CoverAmbient key={it.id} src={coverOf(it)} radius={3} blur={10} spread={1} alphaFactor={0.7}>
                  <button
                    onClick={() => { if (selectMode) onToggleSelect?.(it.id); else onOpenItem(it); }}
                    onMouseEnter={(e) => startHover(e, it)}
                    onMouseLeave={clearHover}
                    onContextMenu={(e) => onContextMenu?.(e, it)}
                    title={it.title}
                    aria-pressed={selected || undefined}
                    data-narrow={w < 20 ? "1" : undefined}
                    className={"shelf-book shrink-0" + (selected ? " shelf-book-selected" : "")}
                    style={{
                      "--sw": w + "px", height: 210,
                      backgroundColor: color, cursor: "pointer",
                    }}>
                    {selectMode && (
                      <span className="shelf-book-mark" data-selected={selected ? "1" : "0"}>
                        {selected ? "✓" : ""}
                      </span>
                    )}
                    <span className="shelf-book-title"
                      style={{
                        position: "absolute", inset: 0, zIndex: 1,
                        display: "flex", alignItems: "flex-start", justifyContent: "center",
                        writingMode: "vertical-rl", textOrientation: "mixed",
                        padding: "22px 5px 8px", fontSize: 11, color: "var(--text)",
                        letterSpacing: 2, lineHeight: 1.3, fontWeight: 600,
                        textAlign: "center", wordBreak: "break-all",
                      }}>
                      {it.title}
                    </span>
                    <span className="shelf-book-foot" aria-hidden />
                  </button>
                  </CoverAmbient>
                );
              })}
            </div>
            {/* 层板（书架板，书站在上面） */}
            <div className="shelf-board" aria-hidden />
          </div>
        </div>
      ))}
      {items.length === 0 && (
        <div className="text-sm py-16" style={{ color: "var(--text-secondary)" }}>
          书架是空的
        </div>
      )}

      {/* hover 抽书预览（fixed 定位，脱离滚动；贴近书本、克制、无大浮卡） */}
      {hover && (
        <div className="fixed z-40" style={{ left: hover.x, top: hover.y, width: 118, pointerEvents: "none" }}
          data-testid="shelf-preview">
          <div className="overflow-hidden"
            style={{
              backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)",
              borderRadius: "var(--radius-cover)",
              boxShadow: "0 10px 24px rgba(0,0,0,0.20)",
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
