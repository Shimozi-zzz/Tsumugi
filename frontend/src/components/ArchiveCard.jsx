// 档案卡片（本轮 Archive Grid 结构性重设计的范本，ADR 0054）
// - 藏品编目号（NO.xxxx 等宽）+ 来源**文字标注**（不再盖在封面上的色块徽章）
// - 容器近直角（6px），封面作为"馆藏实物"在内部保留中等圆角（--radius-sm）
// - 标题用衬线加大字重（排版自信）；编目行细分隔，档案排布感
// - 无封面 → 档案占位（书脊轮廓 + 编目号，不再是无内容的灰色方块）
import React from "react";

/** 藏品编目号：条目入库序号（id）补零，如 NO. 0003。 */
export function catalogNo(it) {
  const n = it && it.id != null ? it.id : 0;
  return String(n).padStart(4, "0");
}

/** 无本地封面时的档案占位：书脊轮廓线 + 编目号，呼应"待上架的档案卡"。 */
export function ArchivePlaceholder({ no }) {
  return (
    <div className="archive-ph" data-testid="archive-placeholder">
      <div className="archive-ph-spine" aria-hidden>
        <span className="archive-ph-spine-rule" />
      </div>
      <span className="archive-ph-no">藏 · {no}</span>
    </div>
  );
}

export default function ArchiveCard({
  it, cover, onOpen, onContextMenu, onReview, onDelete,
  selected = false, selectMode = false, onToggleSelect, onReplaceCover,
}) {
  const no = catalogNo(it);
  const handleClick = () => { if (selectMode) onToggleSelect?.(); else onOpen?.(); };
  return (
    <div className={"archive-card group" + (selected ? " archive-card-selected" : "")}
      onClick={handleClick}
      onContextMenu={onContextMenu}
      data-testid="archive-card">
      <div className="archive-card-cover" style={{ aspectRatio: "3/4" }}>
        {cover ? (
          <img src={cover} alt={it.title} loading="lazy" className="archive-card-img"
            onError={(e) => { e.target.style.display = "none"; }} />
        ) : (
          <ArchivePlaceholder no={no} />
        )}
        {selectMode && (
          <span className="absolute top-1.5 left-1.5 w-5 h-5 rounded-full flex items-center justify-center text-[11px] z-10"
            style={{ backgroundColor: selected ? "var(--accent)" : "rgba(255,255,255,0.9)",
              color: selected ? "#fff" : "var(--text-secondary)", border: "1px solid var(--accent)" }}>
            {selected ? "✓" : ""}
          </span>
        )}
        {onReplaceCover && (
          <button onClick={(e) => { e.stopPropagation(); onReplaceCover(); }}
            className="archive-card-cover-btn">换封面</button>
        )}
      </div>
      <div className="archive-card-info">
        {/* 编目行：藏品号 + 来源（文字标注，非封面色块） */}
        <div className="archive-card-meta">
          <span className="archive-card-no" title={`藏品号 ${no}`}>NO. {no}</span>
          {it.source !== "local" && (
            <span className="archive-card-source" title={`来源：${it.source}`}>{it.source}</span>
          )}
        </div>
        <h3 className="archive-card-title tsm-heading">{it.title}</h3>
        <div className="archive-card-actions">
          <span className="archive-card-type">
            {it.type === "image" ? "图片" : it.type === "note" ? `${it.chunks_count || 0} 块` : ""}
          </span>
          <div className="flex items-center gap-2">
            {onReview && (
              <button className="archive-card-action ac" onClick={(e) => { e.stopPropagation(); onReview(); }}>书评</button>
            )}
            {onDelete && (
              <button className="archive-card-action dn" onClick={(e) => { e.stopPropagation(); onDelete(); }}>删除</button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
