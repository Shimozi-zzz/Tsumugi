// 只读书评弹层（复用组件：Phase B 作品时间轴点击 + Phase E 往年今日唤起共用）
// 给定 itemId + review 的 source_ref，拉该书评全文，用 .doc markdown 排版只读展示。
// 轻量覆盖层，不打断浏览流。
import React, { useEffect, useState } from "react";
import { fetchItemReviews } from "../api.js";
import { renderMarkdown } from "../markdown.js";

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (!Number.isNaN(d.getTime())) {
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }
  return String(iso).slice(0, 10);
}

export default function MemoryReviewModal({ itemId, sourceRef, onClose }) {
  const [state, setState] = useState({ review: null, error: "" });

  useEffect(() => {
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
  }, [itemId, sourceRef]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6"
      style={{ backgroundColor: "rgba(8,10,18,0.55)" }}
      onClick={onClose}>
      <div className="w-full max-w-lg max-h-[80vh] overflow-y-auto rounded-2xl p-5"
        style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", boxShadow: "var(--shadow-md)" }}
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="min-w-0">
            <div className="text-sm font-medium" style={{ color: "var(--text)" }}>
              {state.review?.title || "书评"}
            </div>
            {state.review && (
              <div className="text-[11px] mt-1 flex flex-wrap gap-x-3 gap-y-1"
                style={{ color: "var(--text-secondary)" }}>
                {state.review.rating != null && <span>评分 ★{state.review.rating}</span>}
                {state.review.status && <span>状态 {state.review.status}</span>}
                <span>{formatDate(state.review.created_at)}</span>
              </div>
            )}
          </div>
          <button onClick={onClose} title="关闭"
            className="shrink-0 px-2 py-0.5 rounded-lg text-sm"
            style={{ color: "var(--text-secondary)" }}>✕</button>
        </div>
        <div className="doc text-[13px] leading-relaxed"
          dangerouslySetInnerHTML={{
            __html: state.review
              ? renderMarkdown(state.review.content)
              : `<p style="color:var(--text-secondary)">${state.error || "加载中…"}</p>`,
          }} />
      </div>
    </div>
  );
}
