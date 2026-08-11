// 档案卡片 · 编目抽屉索书卡（ADR 0054/0056/0060/0061/0069）
// Phase 2-2（ADR 0069）：ArchiveCard 视觉层级改为「书」——封面是第一视觉锚点，
// 之下依次：衬线标题 → 编目行（NO. + 来源）→ 索书卡元数据行（─ 编目号/来源/记录）→
// 次级操作。保留全部信息与交互；新增键盘焦点（Enter/Space 打开，--focus-ring）。
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
  const handleKey = (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); handleClick(); }
  };
  return (
    <div className={"archive-card group" + (selected ? " archive-card-selected" : "")}
      onClick={handleClick}
      onKeyDown={handleKey}
      role="button"
      tabIndex={0}
      aria-label={it.title}
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
      <div className="archive-card-body">
        <h3 className="archive-card-title tsm-heading">{it.title}</h3>
        <div className="archive-card-meta">
          <span className="archive-card-no" title={`藏品号 ${no}`}>NO. {no}</span>
          {it.source !== "local" && (
            <span className="archive-card-source">{it.source}</span>
          )}
        </div>
        <div className="archive-card-lines" data-testid="archive-card-lines">
          <span>─ 编目号 {no}</span>
          <span>─ 来源 {it.source === "local" ? "本地笔记" : it.source}</span>
          {it.chunks_count != null && <span>─ 记录 {it.chunks_count} 条</span>}
        </div>
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
