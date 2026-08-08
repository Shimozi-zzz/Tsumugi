// 角色墙：跨已收藏作品聚合角色，点击角色看关联作品，作品可点回详情
// ADR 0032：选中角色时给出其声优的"查看声优图谱"入口
import React, { useEffect, useState } from "react";
import { fetchCharacters } from "../api.js";

export default function CharacterWall({ refreshKey, onOpenWork, onOpenVoice }) {
  const [chars, setChars] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null); // 选中的角色（显示其作品）

  useEffect(() => {
    setLoading(true);
    fetchCharacters()
      .then(setChars)
      .catch(() => setChars([]))
      .finally(() => setLoading(false));
  }, [refreshKey]);

  if (loading) {
    return <div className="text-sm" style={{ color: "var(--text-secondary)" }}>加载中…</div>;
  }
  if (chars.length === 0) {
    return (
      <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
        还没有角色数据。去「问答」里搜索并收藏一部作品（如 Bangumi/萌娘百科），
        角色会在这里汇总展示。
      </div>
    );
  }

  return (
    <div>
      {selected && (
        <div className="mb-4 rounded-2xl p-4"
          style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)" }}>
          <div className="flex items-center gap-3">
            {selected.image_url && (
              <img src={selected.image_url} alt={selected.name}
                className="w-14 h-19 rounded-lg object-cover shrink-0"
                style={{ width: 56, aspectRatio: "3/4", background: "var(--card-thumb)" }}
                onError={(e) => { e.target.style.display = "none"; }} />
            )}
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium" style={{ color: "var(--text)" }}>{selected.name}</div>
              <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
                {selected.relation ? `${selected.relation} · ` : ""}{selected.source}
                {selected.actors && selected.actors.length > 0 ? ` · 声优：${selected.actors.join("、")}` : ""}
              </div>
              {selected.summary && (
                <div className="text-xs mt-1 line-clamp-2" style={{ color: "var(--text-secondary)" }}>{selected.summary}</div>
              )}
            </div>
            <button onClick={() => setSelected(null)}
              className="text-xs px-2 py-1 rounded-lg shrink-0"
              style={{ color: "var(--text-secondary)" }}>收起</button>
          </div>
          {/* ADR 0032：声优 → 一键跳转声优关系图谱 */}
          {selected.actors && selected.actors.length > 0 && (
            <>
              <div className="text-[11px] mt-3 mb-1.5 tracking-wider" style={{ color: "var(--accent)" }}>声优（点名字看关系图谱）</div>
              <div className="flex flex-wrap gap-1.5">
                {(selected.actors || []).map((a) => (
                  <button key={a} onClick={() => onOpenVoice?.(a)}
                    className="px-2 py-1 rounded-full text-[11px]"
                    style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
                    {a}
                  </button>
                ))}
              </div>
            </>
          )}
          <div className="text-[11px] mt-3 mb-1.5 tracking-wider" style={{ color: "var(--accent)" }}>出自作品</div>
          <div className="flex flex-wrap gap-2">
            {(selected.works || []).map((w) => (
              <button key={w.item_id} onClick={() => onOpenWork(w)}
                className="flex items-center gap-2 px-2.5 py-1.5 rounded-xl text-xs text-left transition-colors"
                style={{ backgroundColor: "rgba(255,255,255,0.06)", border: "1px solid var(--panel-border)", color: "var(--text)" }}>
                {w.image_url && (
                  <img src={w.image_url} alt="" className="w-6 h-8 object-cover rounded"
                    onError={(e) => { e.target.style.display = "none"; }} />
                )}
                <span className="max-w-[180px] truncate">{w.title}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))" }}>
        {chars.map((c) => {
          const active = selected && (c.id ?? c.name) === (selected.id ?? selected.name) && c.source === selected.source;
          return (
            <button key={`${c.source}-${c.id ?? c.name}`} onClick={() => setSelected(c)}
              className="text-left transition-colors"
              style={{
                borderRadius: 16, overflow: "hidden",
                border: active ? "1px solid var(--accent)" : "1px solid var(--panel-border)",
                backgroundColor: "var(--card-bg)",
              }}>
              {c.image_url ? (
                <img src={c.image_url} alt={c.name} loading="lazy"
                  className="w-full object-cover" style={{ aspectRatio: "3/4", background: "var(--card-thumb)" }}
                  onError={(e) => { e.target.style.display = "none"; }} />
              ) : (
                <div className="w-full flex items-center justify-center text-2xl"
                  style={{ aspectRatio: "3/4", background: "var(--card-thumb)", color: "var(--accent)" }}>
                  {(c.name || "?").charAt(0)}
                </div>
              )}
              <div className="px-2 py-1.5">
                <div className="text-xs font-medium truncate" style={{ color: "var(--card-text)" }}>{c.name}</div>
                <div className="text-[10px]" style={{ color: "var(--text-secondary)" }}>
                  {c.source}{c.works.length > 1 ? ` · ${c.works.length} 部` : ""}
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
