// 作品记忆时间轴（Phase B / ADR 0042）
// 调用 Phase A 的 /items/{id}/memories 接口，展示该作品的全部 Memory。
// - 排序：**正序（旧→新）**——"回望"这段关系的开始到现在，读起来像一部
//   编年史（理由见 docs/decisions/0042-memory-timeline.md）；
// - source_type=review 的记忆可点击：只读弹出对应书评全文（复用 renderMarkdown +
//   .doc 样式），不打断主从浏览流；未来 text/image/collection 等来源无需弹窗，降级为不可点；
// - 空状态：刚收藏还没写过书评时给引导文案，不显示空白。
import React, { useEffect, useState } from "react";
import { fetchItemMemories, fetchItemReviews } from "../api.js";
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

export default function MemoryTimeline({ itemId }) {
  const [memories, setMemories] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [openReview, setOpenReview] = useState(null); // {mem, review|null, error}

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

  // 点击 review 记忆 → 拉该作品书评列表，按 source_ref 找到对应 review，只读展示
  async function openMemory(mem) {
    if (mem.source_type !== "review") return;
    setOpenReview({ mem, review: null, error: "" });
    try {
      const reviews = await fetchItemReviews(itemId);
      const review = (reviews || []).find((r) => r.id === mem.source_ref) || null;
      setOpenReview({ mem, review, error: review ? "" : "未找到对应书评" });
    } catch (e) {
      setOpenReview({ mem, review: null, error: e.message });
    }
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

      {/* 只读书评弹层（复用 .doc markdown 样式；轻量覆盖，不打断主从浏览） */}
      {openReview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6"
          style={{ backgroundColor: "rgba(8,10,18,0.55)" }}
          onClick={() => setOpenReview(null)}>
          <div className="w-full max-w-lg max-h-[80vh] overflow-y-auto rounded-2xl p-5"
            style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", boxShadow: "var(--shadow-md)" }}
            onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between gap-3 mb-3">
              <div className="min-w-0">
                <div className="text-sm font-medium" style={{ color: "var(--text)" }}>
                  {openReview.review?.title || "书评"}
                </div>
                {openReview.review && (
                  <div className="text-[11px] mt-1 flex flex-wrap gap-x-3 gap-y-1"
                    style={{ color: "var(--text-secondary)" }}>
                    {openReview.review.rating != null && <span>评分 ★{openReview.review.rating}</span>}
                    {openReview.review.status && <span>状态 {openReview.review.status}</span>}
                    <span>{formatDate(openReview.review.created_at)}</span>
                  </div>
                )}
              </div>
              <button onClick={() => setOpenReview(null)} title="关闭"
                className="shrink-0 px-2 py-0.5 rounded-lg text-sm"
                style={{ color: "var(--text-secondary)" }}>✕</button>
            </div>
            <div className="doc text-[13px] leading-relaxed"
              dangerouslySetInnerHTML={{
                __html: openReview.review
                  ? renderMarkdown(openReview.review.content)
                  : `<p style="color:var(--text-secondary)">${openReview.error || "加载中…"}</p>`,
              }} />
          </div>
        </div>
      )}
    </>
  );
}
