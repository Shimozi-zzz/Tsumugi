// Review 读后感/书评面板（浮层）：文档式书写体验（宽画布 + Markdown 写/预览切换）
// 查看已有（Markdown 渲染成文档）+ 新建/编辑；spoiler 折叠；评分对比
import React, { useEffect, useRef, useState } from "react";
import { fetchItemReviews, createReview, updateReview, deleteReview } from "../api.js";
import { renderMarkdown } from "../markdown.js";

const STATUSES = ["想看", "在看", "看完", "搁置", "弃坑"];
const DEFAULT_FONT = 15;
const FONT_SIZES = [14, 15, 16, 18, 20];

// Markdown 编辑器工具栏：围绕选区插入语法
const TOOLS = [
  { label: "B", title: "加粗", before: "**", after: "**", placeholder: "加粗文字" },
  { label: "I", title: "斜体", before: "*", after: "*", placeholder: "斜体文字" },
  { label: "S", title: "删除线", before: "~~", after: "~~", placeholder: "文字" },
  { label: "H", title: "小标题", before: "\n## ", after: "\n", placeholder: "标题" },
  { label: "•", title: "列表", before: "\n- ", after: "", placeholder: "列表项" },
  { label: "❝", title: "引用", before: "\n> ", after: "\n", placeholder: "引用内容" },
  { label: "`", title: "行内代码", before: "`", after: "`", placeholder: "code" },
  { label: "⌁", title: "代码块", before: "\n```\n", after: "\n```\n", placeholder: "代码" },
  { label: "🔗", title: "链接", before: "[", after: "](https://)", placeholder: "链接文字" },
];

function fmtDate(s) {
  if (!s) return "";
  return s.replace("T", " ").slice(0, 16);
}

// 自动增高 textarea：让正文像一张文档页面那样随内容生长
function useAutoGrow() {
  const ref = useRef(null);
  const grow = () => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  };
  return { ref, grow };
}

export default function ReviewPanel({ item, onClose, refreshItems }) {
  const [reviews, setReviews] = useState([]);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [expandedSpoilers, setExpandedSpoilers] = useState(new Set());
  const [preview, setPreview] = useState(false);
  const [form, setForm] = useState({ title: "", content: "", rating: "", status: "", spoiler: false, font_size: DEFAULT_FONT });
  const [saving, setSaving] = useState(false);
  const contentRef = useAutoGrow();

  const load = () => fetchItemReviews(item.id).then(setReviews).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [item.id]);

  // 围绕 textarea 选区插入 Markdown 语法（编辑器工具栏）
  function applyTool(tool) {
    const el = contentRef.ref.current;
    if (!el) return;
    const s = el.selectionStart ?? 0;
    const e = el.selectionEnd ?? 0;
    const value = form.content;
    const sel = value.slice(s, e) || tool.placeholder || "";
    const next = value.slice(0, s) + tool.before + sel + tool.after + value.slice(e);
    setForm((f) => ({ ...f, content: next }));
    requestAnimationFrame(() => {
      el.focus();
      const ns = s + tool.before.length;
      el.setSelectionRange(ns, ns + sel.length);
      contentRef.grow();
    });
  }

  function openNew() {
    setEditingId(null);
    setForm({ title: "", content: "", rating: "", status: "", spoiler: false, font_size: DEFAULT_FONT });
    setPreview(false);
    setShowForm(true);
    setTimeout(() => contentRef.ref.current?.focus(), 30);
  }
  function openEdit(r) {
    setEditingId(r.id);
    setForm({
      title: r.title || "",
      content: r.content,
      rating: r.rating == null ? "" : String(r.rating),
      status: r.status || "",
      spoiler: r.spoiler,
      font_size: r.font_size || DEFAULT_FONT,
    });
    setPreview(false);
    setShowForm(true);
    setTimeout(() => contentRef.grow(), 30);
  }

  async function submit(e) {
    e.preventDefault();
    if (!form.content.trim()) { setError("内容不能为空"); return; }
    setSaving(true);
    setError("");
    const payload = {
      content: form.content,
      title: form.title.trim() || undefined,
      rating: form.rating === "" ? undefined : Number(form.rating),
      status: form.status || undefined,
      spoiler: form.spoiler,
      font_size: form.font_size || undefined,
    };
    try {
      if (editingId) await updateReview(editingId, payload);
      else await createReview(item.id, payload);
      setShowForm(false);
      setEditingId(null);
      setPreview(false);
      await load();
      refreshItems?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function remove(r) {
    if (!window.confirm("确认删除这条书评？")) return;
    try {
      await deleteReview(r.id);
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  function toggleSpoiler(id) {
    setExpandedSpoilers((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  // 我的平均分：全部 Review 评分（忽略未打分）的均值；无打分则 null
  const rated = reviews.filter((r) => r.rating != null).map((r) => r.rating);
  const myAvg = rated.length > 0 ? (rated.reduce((a, b) => a + b, 0) / rated.length).toFixed(1) : null;
  const publicRating = reviews.find((r) => r.public_rating != null)?.public_rating ?? null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(10,12,20,0.5)" }}
      onClick={onClose}>
      <div className="desk-askbar flex flex-col w-full max-w-3xl max-h-[86vh]"
        onClick={(e) => e.stopPropagation()}
        style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)" }}>
        <div className="flex items-center justify-between px-6 py-4 border-b"
          style={{ borderColor: "var(--panel-border)" }}>
          <div className="min-w-0">
            <h3 className="text-sm font-medium truncate">书评 · {item.title}</h3>
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              {item.source !== "local" && (
                <span className="text-[11px] px-1.5 py-0.5 rounded-full"
                  style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>{item.source}</span>
              )}
              {publicRating != null && (
                <span className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                  大众 ★{publicRating}
                </span>
              )}
              {myAvg != null ? (
                <span className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                  我的平均 ★{myAvg}（{rated.length} 条）
                </span>
              ) : reviews.length > 0 ? (
                <span className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                  我的评分：暂无评分
                </span>
              ) : null}
            </div>
          </div>
          <button onClick={onClose} className="text-sm px-2 py-0.5 rounded-lg shrink-0"
            style={{ color: "var(--text-secondary)" }}>✕</button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}

          {showForm && (
            <div className="doc-editor" style={{ maxWidth: "70ch", margin: "0 auto" }}>
              <input
                placeholder="标题（可选）"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                className="w-full bg-transparent outline-none font-semibold"
                style={{ fontSize: 20, color: "var(--text)", borderBottom: "1px solid var(--panel-border)", paddingBottom: 10, marginBottom: 12 }}
              />
              <div className="flex items-center gap-1 flex-wrap mb-2 pb-2"
                style={{ borderBottom: "1px solid var(--panel-border)" }}>
                <select
                  value={form.font_size}
                  onChange={(e) => { const v = Number(e.target.value); setForm({ ...form, font_size: v }); requestAnimationFrame(contentRef.grow); }}
                  title="正文字号"
                  className="tsm-input border rounded px-1.5 py-1 text-xs mr-1"
                  style={{ color: "var(--text)" }}>
                  {FONT_SIZES.map((s) => <option key={s} value={s}>{s}px</option>)}
                </select>
                {TOOLS.map((t) => (
                  <button key={t.title} type="button" title={t.title} onClick={() => applyTool(t)}
                    className="px-2 py-1 rounded-lg text-xs hover:opacity-75"
                    style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
                    {t.label}
                  </button>
                ))}
                <span className="text-[10px] ml-auto" style={{ color: "var(--text-secondary)" }}>
                  Markdown · 支持 # 标题、**加粗**、- 列表等
                </span>
              </div>
              {preview ? (
                <div className="doc rounded-xl px-5 py-4 min-h-[40vh]"
                  style={{ backgroundColor: "var(--input-bg)", border: "1px solid var(--panel-border)", fontSize: `${form.font_size}px` }}
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(form.content) || "<p style='color:var(--text-secondary)'>（暂无内容）</p>" }} />
              ) : (
                <textarea
                  ref={contentRef.ref}
                  placeholder={"写下你的感想…\n\n支持 Markdown：**加粗**、## 小标题、- 列表、> 引用，内容会参与知识库检索。"}
                  value={form.content}
                  onChange={(e) => { setForm({ ...form, content: e.target.value }); contentRef.grow(); }}
                  className="w-full bg-transparent outline-none resize-none"
                  style={{
                    fontSize: `${form.font_size}px`, lineHeight: 1.85, color: "var(--text)",
                    minHeight: "40vh",
                  }}
                />
              )}
              <div className="flex items-center gap-3 mt-4 flex-wrap">
                <label className="flex items-center gap-1 text-xs" style={{ color: "var(--text-secondary)" }}>
                  评分
                  <select value={form.rating}
                    onChange={(e) => setForm({ ...form, rating: e.target.value })}
                    className="tsm-input border rounded px-1.5 py-1 text-xs">
                    <option value="">—</option>
                    {[...Array(11)].map((_, i) => <option key={i} value={i}>{i}</option>)}
                  </select>
                </label>
                <label className="flex items-center gap-1 text-xs" style={{ color: "var(--text-secondary)" }}>
                  状态
                  <select value={form.status}
                    onChange={(e) => setForm({ ...form, status: e.target.value })}
                    className="tsm-input border rounded px-1.5 py-1 text-xs">
                    <option value="">—</option>
                    {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </label>
                <label className="flex items-center gap-1 text-xs" style={{ color: "var(--text-secondary)" }}>
                  <input type="checkbox" checked={form.spoiler}
                    onChange={(e) => setForm({ ...form, spoiler: e.target.checked })} />
                  含剧透
                </label>
                <div className="flex-1" />
                <button type="button" onClick={() => setPreview((v) => !v)}
                  className="px-3 py-1.5 rounded-xl text-xs"
                  style={{ backgroundColor: preview ? "var(--accent)" : "var(--accent-soft)",
                    color: preview ? "#fff" : "var(--accent)" }}>
                  {preview ? "返回书写" : "预览"}
                </button>
                <button type="button" onClick={() => { setShowForm(false); setEditingId(null); setPreview(false); }}
                  className="px-3 py-1.5 rounded-xl text-xs"
                  style={{ color: "var(--text-secondary)" }}>取消</button>
                <button onClick={submit} disabled={saving}
                  className="px-4 py-1.5 rounded-xl text-xs font-medium disabled:opacity-40"
                  style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
                  {saving ? "保存中…" : editingId ? "保存修改" : "发布"}
                </button>
              </div>
            </div>
          )}

          {reviews.length === 0 && !showForm && (
            <div className="text-center py-10 text-sm" style={{ color: "var(--text-secondary)" }}>
              还没有书评
            </div>
          )}
          {reviews.map((r) => {
            const isSpoilerExpanded = expandedSpoilers.has(r.id);
            const isSpoiler = r.spoiler;
            return (
              <div key={r.id} className="doc-editor rounded-xl p-4"
                style={{ backgroundColor: "rgba(255,255,255,0.04)", border: "1px solid var(--panel-border)", maxWidth: "70ch", margin: "0 auto" }}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium" style={{ color: "var(--text)" }}>
                      {r.title || "读后感"}
                    </span>
                    {r.rating != null && (
                      <span className="text-xs px-1.5 py-0.5 rounded-full"
                        style={{ backgroundColor: "var(--tag-bg)", color: "var(--tag-text)" }}>
                        ★{r.rating}
                      </span>
                    )}
                    {r.status && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full"
                        style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
                        {r.status}
                      </span>
                    )}
                    {r.public_rating != null && (
                      <span className="text-[10px]" style={{ color: "var(--text-secondary)" }}>
                        大众 ★{r.public_rating} / 我 ★{r.rating ?? "—"}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-[10px]" style={{ color: "var(--text-secondary)" }}>
                      {fmtDate(r.created_at)}
                    </span>
                    <button onClick={() => openEdit(r)} className="text-[11px]"
                      style={{ color: "var(--text-secondary)" }}>编辑</button>
                    <button onClick={() => remove(r)} className="text-[11px]"
                      style={{ color: "var(--danger)" }}>删除</button>
                  </div>
                </div>
                {isSpoiler ? (
                  <div>
                    <button onClick={() => toggleSpoiler(r.id)}
                      className="text-xs px-2.5 py-1 rounded-full"
                      style={{ backgroundColor: "var(--tag-bg)", color: "var(--tag-text)" }}>
                      {isSpoilerExpanded ? "收起剧透内容 ▲" : "含剧透 · 点击展开 ▼"}
                    </button>
                    {isSpoilerExpanded && (
                      <div className="doc mt-2" style={{ fontSize: `${r.font_size || DEFAULT_FONT}px` }}
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(r.content) }} />
                    )}
                  </div>
                ) : (
                  <div className="doc" style={{ fontSize: `${r.font_size || DEFAULT_FONT}px` }}
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(r.content) }} />
                )}
              </div>
            );
          })}
        </div>

        <div className="px-6 py-3 border-t flex justify-end"
          style={{ borderColor: "var(--panel-border)" }}>
          {!showForm && (
            <button onClick={openNew}
              className="px-4 py-1.5 rounded-xl text-sm font-medium"
              style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
              + 写书评
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
