// 作品记忆时间轴（Phase B / ADR 0042；P3 / ADR 0047 扩展：轻量记录/里程碑/情绪/媒体）
// 调用 Phase A 的 /items/{id}/memories 接口，展示该作品的全部 Memory。
// - 排序：**正序（旧→新）**——"回望"这段关系的开始到现在，读起来像一部编年史；
// - 点击：review → 只读书评；text/milestone → 直接展示（summary+情绪+媒体）；
//   collection → 不可点击；text/milestone 可删除（✕）；
// - 空状态：还没有记忆时给引导文案。
import React, { useEffect, useState } from "react";
import { fetchItemMemories, deleteMemory } from "../api.js";
import MemoryReviewModal from "./MemoryReviewModal.jsx";
import { MEMORY_TYPE_LABEL, ArchiveNo } from "./ui.jsx";

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (!Number.isNaN(d.getTime())) {
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }
  return String(iso).slice(0, 10);
}

export default function MemoryTimeline({ itemId, refreshKey = 0 }) {
  const [memories, setMemories] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [openMem, setOpenMem] = useState(null); // 正在只读查看的 Memory（null=关闭）

  useEffect(() => {
    if (itemId == null) { setMemories([]); setError(""); return; }
    let cancelled = false;
    setLoading(true);
    setError("");
    fetchItemMemories(itemId)
      .then((m) => { if (!cancelled) setMemories(m || []); })
      .catch((e) => { if (!cancelled) { setError(e.message); setMemories([]); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [itemId, refreshKey]);

  function openMemory(mem) {
    if (mem.source_type === "collection") return; // 收藏时刻不弹层
    setOpenMem(mem);
  }

  function removeMemory(e, mem) {
    e.stopPropagation();
    deleteMemory(mem.id)
      .then(() => setMemories((prev) => prev.filter((m) => m.id !== mem.id)))
      .catch(() => {});
  }

  let body;
  if (loading) {
    body = <div className="text-[12px]" style={{ color: "var(--text-secondary)" }}>记忆加载中…</div>;
  } else if (error) {
    body = <div className="text-[12px]" style={{ color: "var(--danger)" }}>{error}</div>;
  } else if (memories.length === 0) {
    body = (
      <div className="text-[12px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
        还没有值得被记住的时刻。写下书评或一句轻量记录，这里会出现属于你们的记忆。
      </div>
    );
  } else {
    // API 返回 occurred_at 倒序；时间轴按**正序（旧→新）**展示（ADR 0042：回望叙事）
    const ordered = [...memories].sort((a, b) => {
      const ta = new Date(a.occurred_at).getTime() || 0;
      const tb = new Date(b.occurred_at).getTime() || 0;
      return ta === tb ? (a.id - b.id) : (ta - tb);
    });
    body = (
      <div className="relative pl-5">
        {/* 时间轴线 */}
        <div className="absolute left-[3px] top-2 bottom-2 w-px"
          style={{ backgroundColor: "var(--panel-border)" }} />
        {ordered.map((mem, idx) => {
          const clickable = mem.source_type !== "collection";
          const deletable = mem.source_type === "text" || mem.source_type === "milestone";
          const no = String(idx + 1).padStart(2, "0");
          return (
            <div key={mem.id} className="relative mb-3 last:mb-0">
              <span className="absolute -left-5 top-1.5 w-2 h-2 rounded-full"
                style={{ backgroundColor: clickable ? "var(--accent)" : "var(--text-secondary)", opacity: 0.85 }} />
              <button type="button" onClick={() => openMemory(mem)} disabled={!clickable}
                title={clickable ? "查看这条记忆" : undefined}
                className="block w-full text-left"
                style={{ cursor: clickable ? "pointer" : "default" }}>
                <span className="block text-[10px] tabular-nums tracking-wider"
                  style={{ color: "var(--text-secondary)" }}>
                  <ArchiveNo color="muted" className="mr-1.5">{no}</ArchiveNo>
                  {formatDate(mem.occurred_at)}
                  <span className="ml-1.5 px-1 py-px rounded" style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
                    {MEMORY_TYPE_LABEL[mem.source_type] || mem.source_type}
                  </span>
                  {mem.emotion && <span className="ml-1.5" style={{ color: "var(--text-secondary)" }}>· {mem.emotion}</span>}
                </span>
                <span className="block text-[13px] leading-snug mt-0.5" style={{ color: "var(--text)" }}>
                  {mem.summary || "（无摘要）"}
                </span>
                {(mem.media || []).length > 0 && (
                  <span className="block mt-1">
                    {mem.media.slice(0, 3).map((m) => (
                      <img key={m.id} src={m.url} alt="" className="inline-block mr-1 rounded object-cover align-middle"
                        style={{ width: 44, height: 44, border: "1px solid var(--panel-border)" }} />
                    ))}
                  </span>
                )}
              </button>
              {deletable && (
                <button onClick={(e) => removeMemory(e, mem)} title="删除这条记忆"
                  className="absolute -right-1 top-0 px-1 text-[11px] opacity-0 hover:opacity-100 transition-opacity"
                  style={{ color: "var(--danger)" }}>✕</button>
              )}
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <>
      {body}

      {/* 只读记忆弹层（review 拉书评全文；直接记忆展示 summary+情绪+媒体） */}
      {openMem != null && (
        <MemoryReviewModal itemId={itemId} sourceRef={openMem.source_ref}
          memory={openMem.source_type === "review" ? null : openMem}
          onClose={() => setOpenMem(null)} />
      )}
    </>
  );
}
