// 作品详情弹层：展示 get_detail 的完整信息（封面大图/简介/评分/标签/角色墙）
import React from "react";

function coverOk(url) {
  return url && typeof url === "string";
}

export default function ItemDetailModal({ detail, saved, onClose, onSave, onShare }) {
  if (!detail) return null;
  const chars = Array.isArray(detail.characters) ? detail.characters : [];
  const tags = Array.isArray(detail.tags) ? detail.tags : [];
  const title = detail.title || "未命名";
  const desc = detail.description || "";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(10,12,20,0.5)" }} onClick={onClose}>
      <div className="desk-askbar rounded-2xl p-5 w-full max-w-2xl max-h-[86vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)" }}>
        {/* 头部：来源 / 评分 / 收藏态 */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] px-2 py-0.5 rounded-full"
              style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
              {detail.source || "外部"}
            </span>
            {typeof detail.rating === "number" && (
              <span className="text-xs" style={{ color: "var(--amber, #ffc24b)" }}>大众 ★{detail.rating}</span>
            )}
            {typeof detail.my_rating === "number" && (
              <span className="text-xs" style={{ color: "var(--text-secondary)" }}>我的平均 ★{detail.my_rating}</span>
            )}
            {saved && (
              <span className="text-[11px] px-2 py-0.5 rounded-full"
                style={{ backgroundColor: "var(--tag-bg)", color: "var(--tag-text)" }}>已收藏</span>
            )}
          </div>
          <button onClick={onClose} className="text-sm px-2 py-0.5 rounded-lg"
            style={{ color: "var(--text-secondary)" }}>✕</button>
        </div>

        {/* 封面 + 简介 */}
        <div className="flex gap-4">
          {coverOk(detail.image_url) ? (
            <img src={detail.image_url} alt={title}
              className="w-32 h-44 object-cover rounded-xl shrink-0"
              onError={(e) => { e.target.style.display = "none"; }} />
          ) : (
            <div className="w-32 h-44 rounded-xl shrink-0 flex items-center justify-center text-xl"
              style={{ background: "var(--card-thumb)", color: "var(--accent)" }}>{title[0]}</div>
          )}
          <div className="flex-1 min-w-0">
            <h3 className="text-base font-medium mb-2" style={{ color: "var(--text)" }}>{title}</h3>
            <p className="text-sm whitespace-pre-wrap leading-relaxed max-h-40 overflow-y-auto"
              style={{ color: "var(--text-secondary)" }}>
              {desc || "暂无简介。"}
            </p>
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-3">
                {tags.map((t) => (
                  <span key={t} className="text-[11px] px-2 py-0.5 rounded-full"
                    style={{ backgroundColor: "var(--tag-bg)", color: "var(--tag-text)" }}>{t}</span>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* 角色墙 */}
        {chars.length > 0 && (
          <div className="mt-5">
            <div className="text-[11px] mb-2 tracking-wider" style={{ color: "var(--accent)" }}>登场角色</div>
            <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(96px, 1fr))" }}>
              {chars.map((c, i) => (
                <div key={c.id ?? i} className="flex flex-col items-center text-center"
                  style={{ borderRadius: 14, overflow: "hidden", border: "1px solid var(--panel-border)", backgroundColor: "rgba(255,255,255,0.04)" }}>
                  {coverOk(c.image_url) ? (
                    <img src={c.image_url} alt={c.name || ""}
                      className="w-full object-cover"
                      style={{ aspectRatio: "3/4", background: "var(--card-thumb)" }}
                      onError={(e) => { e.target.style.display = "none"; }} />
                  ) : (
                    <div className="w-full flex items-center justify-center text-xl"
                      style={{ aspectRatio: "3/4", background: "var(--card-thumb)", color: "var(--accent)" }}>
                      {(c.name || "?").charAt(0)}
                    </div>
                  )}
                  <div className="px-1 py-1 w-full">
                    <div className="text-[11px] leading-tight truncate" style={{ color: "var(--text)" }}>{c.name}</div>
                    {c.relation && (
                      <div className="text-[10px]" style={{ color: "var(--text-secondary)" }}>{c.relation}</div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {onSave && (
          <button onClick={onSave}
            className="mt-4 px-3 py-1.5 rounded-xl text-sm font-medium"
            style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
            收藏入库
          </button>
        )}
        {saved && onShare && (
          <button onClick={() => onShare(detail.id)}
            className="mt-4 ml-2 px-3 py-1.5 rounded-xl text-sm font-medium"
            style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
            生成安利卡
          </button>
        )}
      </div>
    </div>
  );
}
