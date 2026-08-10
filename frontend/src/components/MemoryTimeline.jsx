// 作品记忆时间轴（Phase B / ADR 0042）
// 调用 Phase A 的 /items/{id}/memories 接口，展示该作品的全部 Memory。
// - 排序：**正序（旧→新）**——"回望"这段关系的开始到现在，读起来像一部
//   编年史（理由见 docs/decisions/0042-memory-timeline.md）；
// - source_type=review 的记忆可点击：复用 MemoryReviewModal 只读展示完整书评；
// - 空状态：刚收藏还没写过书评时给引导文案，不显示空白。
import React, { useEffect, useState } from "react";
import { fetchItemMemories } from "../api.js";
import MemoryReviewModal from "./MemoryReviewModal.jsx";

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (!Number.isNaN(d.getTime())) {
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }
  return String(iso).slice(0, 10);
}

export default function MemoryTimeline({ itemId }) {
  const [memories, setMemories] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [openRef, setOpenRef] = useState(null); // 正在只读查看的 review id（null=关闭）

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
  }, [itemId]);

  function openMemory(mem) {
    if (mem.source_type !== "review") return;
    setOpenRef(mem.source_ref);
  }

  let body;
  if (loading) {
    body = <div className="text-[12px]" style={{ color: "var(--text-secondary)" }}>记忆加载中…</div>;
  } else if (error) {
    body = <div className="text-[12px]" style={{ color: "var(--danger)" }}>{error}</div>;
  } else if (memories.length === 0) {
    body = (
      <div className="text-[12px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
        还没有值得被记住的时刻。写下第一篇书评，这里会出现属于你们的记忆。
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
        {ordered.map((mem) => {
          const clickable = mem.source_type === "review";
          return (
            <button key={mem.id} type="button"
              onClick={() => openMemory(mem)}
              disabled={!clickable}
              title={clickable ? "查看完整书评" : undefined}
              className="relative mb-3 block w-full text-left last:mb-0"
              style={{ cursor: clickable ? "pointer" : "default" }}>
              <span className="absolute -left-5 top-1.5 w-2 h-2 rounded-full"
                style={{ backgroundColor: clickable ? "var(--accent)" : "var(--text-secondary)", opacity: 0.85 }} />
              <span className="block text-[10px] tabular-nums tracking-wider"
                style={{ color: "var(--text-secondary)" }}>{formatDate(mem.occurred_at)}</span>
              <span className="block text-[13px] leading-snug mt-0.5"
                style={{ color: "var(--text)" }}>{mem.summary || "（无摘要）"}</span>
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <>
      {body}

      {/* 只读书评弹层（复用 MemoryReviewModal，Phase E 同样复用） */}
      {openRef != null && (
        <MemoryReviewModal itemId={itemId} sourceRef={openRef} onClose={() => setOpenRef(null)} />
      )}
    </>
  );
}
