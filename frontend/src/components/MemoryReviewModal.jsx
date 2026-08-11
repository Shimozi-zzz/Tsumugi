// 记忆只读弹层（复用组件：Phase B 作品时间轴 / Phase E 往年今日 / P3 轻量记录 共用）
// - source_type=review（或未传 memory）：按 itemId+sourceRef 拉书评全文，.doc markdown 展示；
// - 直接记忆（text/milestone，P3 / ADR 0047）：直接展示 summary + 情绪 + 媒体图片，不拉书评。
import React, { useEffect, useState } from "react";
import { fetchItemReviews } from "../api.js";
import { renderMarkdown } from "../markdown.js";
import { MEMORY_TYPE_LABEL } from "./ui.jsx";

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (!Number.isNaN(d.getTime())) {
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }
  return String(iso).slice(0, 10);
}

export default function MemoryReviewModal({ itemId, sourceRef, memory, onClose }) {
  const isDirect = !!memory && memory.source_type !== "review";
  const [state, setState] = useState({ review: null, error: "" });

  useEffect(() => {
    if (isDirect) return; // 直接记忆无需拉取
    let cancelled = false;
    setState({ review: null, error: "" });
    fetchItemReviews(itemId)
      .then((reviews) => {
        if (cancelled) return;
        const review = (reviews || []).find((r) => r.id === sourceRef) || null;
        setState({ review, error: review ? "" : "未找到对应书评" });
      })
      .catch((e) => { if (!cancelled) setState({ review: null, error: e.message }); });
    return () => { cancelled = true; };
  }, [itemId, sourceRef, isDirect]);

  const title = isDirect
    ? (MEMORY_TYPE_LABEL[memory.source_type] || "记录")
    : (state.review?.title || "书评");
  const meta = isDirect ? (
    <div className="text-[11px] mt-1 flex flex-wrap gap-x-3 gap-y-1" style={{ color: "var(--text-secondary)" }}>
      {memory.emotion && <span>情绪 {memory.emotion}</span>}
      <span>{formatDate(memory.occurred_at)}</span>
    </div>
  ) : state.review ? (
    <div className="text-[11px] mt-1 flex flex-wrap gap-x-3 gap-y-1" style={{ color: "var(--text-secondary)" }}>
      {state.review.rating != null && <span>评分 ★{state.review.rating}</span>}
      {state.review.status && <span>状态 {state.review.status}</span>}
      <span>{formatDate(state.review.created_at)}</span>
    </div>
  ) : null;

  const contentHtml = isDirect
    ? renderMarkdown(memory.summary || "")
    : (state.review
        ? renderMarkdown(state.review.content)
        : `<p style="color:var(--text-secondary)">${state.error || "加载中…"}</p>`);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6"
      style={{ backgroundColor: "rgba(8,10,18,0.55)" }}
      onClick={onClose}>
      <div className="w-full max-w-lg max-h-[80vh] overflow-y-auto p-5"
        style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", boxShadow: "var(--shadow-md)", borderRadius: "var(--radius-floating)" }}
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="min-w-0">
            <div className="text-sm font-medium" style={{ color: "var(--text)" }}>{title}</div>
            {meta}
          </div>
          <button onClick={onClose} title="关闭"
            className="shrink-0 px-2 py-0.5 rounded-lg text-sm"
            style={{ color: "var(--text-secondary)" }}>✕</button>
        </div>
        {isDirect && (memory.media || []).length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3">
            {memory.media.map((m) => (
              <img key={m.id} src={m.url} alt="" className="rounded-lg object-cover"
                style={{ maxWidth: 160, maxHeight: 120, border: "1px solid var(--panel-border)" }} />
            ))}
          </div>
        )}
        <div className="doc text-[13px] leading-relaxed" dangerouslySetInnerHTML={{ __html: contentHtml }} />
      </div>
    </div>
  );
}
