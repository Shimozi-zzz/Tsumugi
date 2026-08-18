// 人物面板（Phase 13-B）：Staff / Character 的本地人物详情 + 出演作品
// - 只展示本地已收藏作品，不调用 Provider
// - works 可点击进入 ItemDetailPanel
import React, { useEffect, useState } from "react";
import { fetchStaffPerson, fetchCharacterPerson } from "../api.js";
import { PROVIDER_LABELS } from "./ui.jsx";

export default function PersonPanel({ person, onOpenWork, onClose }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (!person) return;
    let cancelled = false;
    setData(null);
    setErr(null);
    const req = person.type === "character"
      ? fetchCharacterPerson(person.source, person.external_id)
      : fetchStaffPerson(person.source, person.external_id);
    req
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setErr(e.message); });
    return () => { cancelled = true; };
  }, [person]);

  if (!person) return null;
  return (
    <div style={{ padding: 16 }}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <h3 className="text-sm font-semibold" style={{ color: "var(--text)" }}>{person.name}</h3>
          <span className="tsm-tag" style={{ fontSize: 10, padding: "0 6px", borderRadius: "var(--radius-control)" }}>
            {person.type === "character" ? "角色" : "Staff"}
          </span>
          <span className="tsm-tag" style={{ fontSize: 10, padding: "0 6px", borderRadius: "var(--radius-control)" }}>
            {PROVIDER_LABELS[person.source] || person.source}
          </span>
        </div>
        <button onClick={onClose} title="关闭" className="text-sm px-1"
          style={{ color: "var(--text-secondary)", borderRadius: "var(--radius-control)" }}>✕</button>
      </div>

      {err ? (
        <div className="text-xs" style={{ color: "var(--danger)" }}>{err}</div>
      ) : !data ? (
        <div className="text-xs" style={{ color: "var(--text-secondary)" }}>加载中…</div>
      ) : (
        <>
          {person.type === "character" && (
            <div className="flex gap-3 mb-3">
              {data.image_url ? (
                <img src={data.image_url} alt="" loading="lazy"
                  style={{ width: 48, height: 64, borderRadius: "var(--radius-cover)", objectFit: "cover" }} />
              ) : null}
              <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                {data.relation ? <div>关系：{data.relation}</div> : null}
                {(data.actors || []).length > 0 ? <div>CV：{(data.actors || []).join(" / ")}</div> : null}
                {data.summary ? <div style={{ marginTop: 2, color: "var(--text)" }}>{data.summary.slice(0, 120)}</div> : null}
              </div>
            </div>
          )}
          {/* Phase 13-C：Staff 身份聚合——从本地作品 role 提炼（客户端计算，零新增请求） */}
          {person.type === "staff" && (() => {
            const roles = [...new Set((data.works || []).map((w) => w.role).filter(Boolean))];
            if (!roles.length) return null;
            return (
              <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 8 }}>
                身份：{roles.join(" / ")}
              </div>
            );
          })()}

          <div className="wd-chars-title" style={{ marginBottom: 6 }}>
            {person.type === "character" ? "出演作品" : "相关作品"} · {(data.works || []).length}
          </div>
          {(data.works || []).length === 0 ? (
            <div className="text-xs" style={{ color: "var(--text-secondary)" }}>暂无本地收藏作品</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {(data.works || []).map((w, i) => (
                <button key={i} type="button" onClick={() => w.item_id != null && onOpenWork && onOpenWork(w.item_id)}
                  disabled={w.item_id == null}
                  style={{ display: "flex", alignItems: "center", gap: 8, textAlign: "left", padding: "5px 6px", borderRadius: "var(--radius-control)", border: "none", background: "transparent", cursor: w.item_id != null ? "pointer" : "default", width: "100%", fontSize: 12 }}>
                  <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text)" }}>{w.title}</span>
                  {w.year ? <span style={{ color: "var(--ink-2)", fontSize: 10, flexShrink: 0 }}>{w.year}</span> : null}
                  {w.role || w.relation ? <span className="tsm-tag" style={{ fontSize: 9, padding: "0 5px", flexShrink: 0 }}>{w.role || w.relation}</span> : null}
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
