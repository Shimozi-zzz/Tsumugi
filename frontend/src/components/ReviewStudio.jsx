// 沉浸式书评工作室（Media Review & Note-taking Studio）
// Violet Obsidian 玻璃拟态：左参考区（元数据/角色/记录）+ 右编辑器（Markdown 工具栏/字号/浮动引用卡/评分）
import React, { useEffect, useRef, useState } from "react";
import {
  fetchItemDetail, fetchItemReviews, createReview, updateReview, deleteReview, filePathToUrl,
} from "../api.js";
import { renderMarkdown } from "../markdown.js";
import { toast } from "../toast.js";

const STATUSES = ["想看", "在看", "看完", "搁置", "弃坑"];
const DEFAULT_FONT = 15;
const FONT_SIZES = [14, 15, 16, 18, 20];
const TABS = [
  { key: "overview", label: "Overview" },
  { key: "records", label: "Records" },
  { key: "archive", label: "Archive" },
  { key: "memories", label: "Memories" },
];
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

const emptyForm = { title: "", content: "", rating: "", status: "", spoiler: false, font_size: DEFAULT_FONT };

export default function ReviewStudio({ item, onClose, refreshItems }) {
  const [detail, setDetail] = useState(null);
  const [reviews, setReviews] = useState([]);
  const [tab, setTab] = useState("overview");
  const [editingId, setEditingId] = useState(null);
  const [preview, setPreview] = useState(false);
  const [form, setForm] = useState({ ...emptyForm });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const contentRef = useAutoGrow();

  useEffect(() => {
    fetchItemDetail(item.id).then(setDetail).catch(() => {});
    loadReviews();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  function loadReviews() {
    fetchItemReviews(item.id).then(setReviews).catch((e) => setError(e.message));
  }

  function startNew() {
    setEditingId(null);
    setForm({ ...emptyForm });
    setPreview(false);
    setTimeout(() => contentRef.ref.current?.focus(), 30);
  }
  function startEdit(r) {
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
    requestAnimationFrame(contentRef.grow);
  }

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

  async function submit() {
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
      toast.success(editingId ? "已保存修改" : "书评已发布");
      setEditingId(null);
      setPreview(false);
      await loadReviews();
      refreshItems?.();
    } catch (err) {
      setError(err.message);
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function remove(r) {
    if (!window.confirm("确认删除这条书评？")) return;
    try {
      await deleteReview(r.id);
      toast.success("已删除");
      await loadReviews();
      if (editingId === r.id) startNew();
    } catch (err) {
      toast.error(err.message);
    }
  }

  const myAvg = (() => {
    const rated = reviews.filter((r) => r.rating != null).map((r) => r.rating);
    return rated.length ? (rated.reduce((a, b) => a + b, 0) / rated.length).toFixed(1) : null;
  })();
  const cover = (detail && (detail.image_url || filePathToUrl(detail?.file_path))) || "";
  const quote = (form.content.match(/^\s*>\s?(.*)$/m) || [])[1];

  return (
    <div className="review-studio fixed inset-0 z-50 overflow-hidden">
      {cover && <div className="rs-bg" style={{ backgroundImage: `url(${cover})` }} />}
      <div className="rs-overlay" />
      <div className="relative h-full w-full flex flex-col" style={{ padding: 18 }}>
        {/* 顶部栏 */}
        <div className="rs-panel flex items-center gap-3 px-4 py-2.5 mb-3">
          <button onClick={onClose} className="text-sm px-2 py-1 rounded-lg hover:opacity-75"
            style={{ color: "var(--rs-text-secondary)" }}>← 返回</button>
          <div className="min-w-0">
            <div className="text-sm font-medium truncate" style={{ color: "var(--rs-text)" }}>
              {detail?.title || item.title}
            </div>
            <div className="text-xs" style={{ color: "var(--rs-text-secondary)" }}>
              {detail?.source || "local"}
              {detail?.rating != null && <> · 大众 ★{detail.rating}</>}
              {myAvg != null && <> · 我的平均 ★{myAvg}（{reviews.length} 条）</>}
            </div>
          </div>
          <div style={{ flex: 1 }} />
          <button onClick={onClose} className="text-sm px-2 py-1 rounded-lg hover:opacity-75"
            style={{ color: "var(--rs-text-secondary)" }}>✕</button>
        </div>

        <div className="grid gap-3 flex-1 min-h-0" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.15fr)" }}>
          {/* 左：参考区 */}
          <div className="rs-panel flex flex-col min-h-0">
            <div className="flex gap-1 px-3 pt-3 pb-2 border-b" style={{ borderColor: "var(--rs-border)" }}>
              {TABS.map((t) => (
                <button key={t.key} onClick={() => setTab(t.key)}
                  className={`rs-tab ${tab === t.key ? "on" : ""}`}>{t.label}</button>
              ))}
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {tab === "overview" && (
                <>
                  <div className="text-xs" style={{ color: "var(--rs-text-secondary)" }}>
                    <div className="mb-2"><b style={{ color: "var(--rs-text)" }}>简介</b></div>
                    <div className="whitespace-pre-wrap leading-relaxed" style={{ fontSize: 13 }}>
                      {detail?.description || "暂无简介。"}
                    </div>
                  </div>
                  {(detail?.tags || []).length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {(detail.tags || []).map((t) => (
                        <span key={t} className="text-[11px] px-2 py-0.5 rounded-full"
                          style={{ backgroundColor: "var(--rs-accent-soft)", color: "var(--rs-accent)" }}>{t}</span>
                      ))}
                    </div>
                  )}
                </>
              )}
              {tab === "records" && (
                <>
                  {reviews.length === 0 && (
                    <div className="text-sm py-8 text-center" style={{ color: "var(--rs-text-secondary)" }}>
                      还没有书评 · 在右侧开始书写
                    </div>
                  )}
                  {reviews.map((r) => (
                    <div key={r.id} className="rounded-xl p-3"
                      style={{ backgroundColor: "rgba(255,255,255,0.04)", border: "1px solid var(--rs-border)" }}>
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium" style={{ color: "var(--rs-text)" }}>{r.title || "读后感"}</span>
                          {r.rating != null && <span className="text-xs" style={{ color: "var(--rs-accent)" }}>★{r.rating}</span>}
                          {r.status && <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ backgroundColor: "var(--rs-accent-soft)", color: "var(--rs-accent)" }}>{r.status}</span>}
                        </div>
                        <div className="flex items-center gap-2">
                          <button onClick={() => startEdit(r)} className="text-[11px]" style={{ color: "var(--rs-text-secondary)" }}>编辑</button>
                          <button onClick={() => remove(r)} className="text-[11px]" style={{ color: "#fda4af" }}>删除</button>
                        </div>
                      </div>
                      {r.spoiler ? (
                        <button onClick={() => { }}
                          className="text-xs px-2 py-1 rounded-full"
                          style={{ backgroundColor: "var(--rs-accent-soft)", color: "var(--rs-accent)" }}>
                          含剧透 · 在编辑器查看
                        </button>
                      ) : (
                        <div className="doc" style={{ fontSize: `${r.font_size || DEFAULT_FONT}px` }}
                          dangerouslySetInnerHTML={{ __html: renderMarkdown(r.content) }} />
                      )}
                    </div>
                  ))}
                </>
              )}
              {tab === "archive" && (
                <>
                  <div className="text-xs" style={{ color: "var(--rs-text-secondary)" }}>角色资料</div>
                  {(detail?.characters || []).length === 0 && (
                    <div className="text-sm" style={{ color: "var(--rs-text-secondary)" }}>暂无角色数据。</div>
                  )}
                  <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(92px, 1fr))" }}>
                    {(detail?.characters || []).map((c, i) => (
                      <div key={c.id ?? i} className="rounded-xl overflow-hidden text-center"
                        style={{ backgroundColor: "rgba(255,255,255,0.04)", border: "1px solid var(--rs-border)" }}>
                        {c.image_url ? (
                          <img src={c.image_url} alt="" className="w-full object-cover" style={{ aspectRatio: "3/4" }}
                            onError={(e) => { e.target.style.display = "none"; }} />
                        ) : (
                          <div className="w-full flex items-center justify-center" style={{ aspectRatio: "3/4", backgroundColor: "rgba(168,85,247,0.12)", color: "var(--rs-accent)" }}>
                            {(c.name || "?").charAt(0)}
                          </div>
                        )}
                        <div className="px-1 py-1">
                          <div className="text-[11px] truncate" style={{ color: "var(--rs-text)" }}>{c.name}</div>
                          {c.relation && <div className="text-[10px]" style={{ color: "var(--rs-text-secondary)" }}>{c.relation}</div>}
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
              {tab === "memories" && (
                <>
                  <div className="text-xs" style={{ color: "var(--rs-text-secondary)" }}>书写时间线</div>
                  {reviews.length === 0 && (
                    <div className="text-sm" style={{ color: "var(--rs-text-secondary)" }}>还没有留下记忆。</div>
                  )}
                  {[...reviews].sort((a, b) => (a.created_at > b.created_at ? 1 : -1)).map((r) => (
                    <div key={r.id} className="flex items-center gap-3 text-sm" style={{ color: "var(--rs-text-secondary)" }}>
                      <span className="text-[11px] w-28 shrink-0" style={{ color: "var(--rs-text)" }}>{fmtDate(r.created_at)}</span>
                      <span>{r.status || "—"}</span>
                      {r.rating != null && <span style={{ color: "var(--rs-accent)" }}>★{r.rating}</span>}
                      <span className="truncate">{r.title || "读后感"}</span>
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>

          {/* 右：编辑器 */}
          <div className="rs-panel relative flex flex-col min-h-0">
            <div className="px-5 pt-4 pb-2">
              <input
                placeholder="标题（可选）"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                className="w-full bg-transparent outline-none font-semibold"
                style={{ fontSize: 20, color: "var(--rs-text)", borderBottom: "1px solid var(--rs-border)", paddingBottom: 10, marginBottom: 12 }}
              />
              <div className="flex items-center gap-1 flex-wrap pb-2" style={{ borderBottom: "1px solid var(--rs-border)" }}>
                <select
                  value={form.font_size}
                  onChange={(e) => { const v = Number(e.target.value); setForm({ ...form, font_size: v }); requestAnimationFrame(contentRef.grow); }}
                  title="正文字号"
                  className="rs-field px-1.5 py-1 text-xs mr-1"
                  style={{ color: "var(--rs-text)" }}>
                  {FONT_SIZES.map((s) => <option key={s} value={s}>{s}px</option>)}
                </select>
                {TOOLS.map((t) => (
                  <button key={t.title} type="button" title={t.title} onClick={() => applyTool(t)}
                    className="px-2 py-1 rounded-lg text-xs hover:opacity-75"
                    style={{ backgroundColor: "var(--rs-accent-soft)", color: "var(--rs-accent)" }}>
                    {t.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex-1 overflow-y-auto px-5">
              {preview ? (
                <div className="doc rounded-xl px-5 py-4"
                  style={{ backgroundColor: "rgba(255,255,255,0.03)", border: "1px solid var(--rs-border)", fontSize: `${form.font_size}px`, minHeight: "52vh" }}
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(form.content) || "<p style='color:var(--rs-text-secondary)'>（暂无内容）</p>" }} />
              ) : (
                <textarea
                  ref={contentRef.ref}
                  placeholder={"写下你的感想…\n\n支持 Markdown：**加粗**、## 小标题、- 列表、> 引用；内容会参与知识库检索。"}
                  value={form.content}
                  onChange={(e) => { setForm({ ...form, content: e.target.value }); contentRef.grow(); }}
                  className="w-full bg-transparent outline-none resize-none"
                  style={{ fontSize: `${form.font_size}px`, lineHeight: 1.85, color: "var(--rs-text)", minHeight: "52vh" }}
                />
              )}
            </div>
            {/* 浮动引用卡 */}
            <div className="rs-quote">
              <div className="text-[10px] mb-1" style={{ color: "var(--rs-accent)" }}>引用卡</div>
              <div className="line-clamp-3">“{quote || "在正文里用 > 写一句引用，会浮现到这里" }”</div>
            </div>
            {/* 底部：评分/状态/操作 */}
            <div className="px-5 py-3 border-t" style={{ borderColor: "var(--rs-border)" }}>
              {error && <p className="text-xs mb-2" style={{ color: "#fda4af" }}>{error}</p>}
              <div className="flex items-center gap-3 flex-wrap">
                <label className="flex items-center gap-1 text-xs" style={{ color: "var(--rs-text-secondary)" }}>
                  评分
                  <select value={form.rating} onChange={(e) => setForm({ ...form, rating: e.target.value })}
                    className="rs-field px-1.5 py-1 text-xs">
                    <option value="">—</option>
                    {[...Array(11)].map((_, i) => <option key={i} value={i}>{i}</option>)}
                  </select>
                </label>
                <label className="flex items-center gap-1 text-xs" style={{ color: "var(--rs-text-secondary)" }}>
                  状态
                  <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}
                    className="rs-field px-1.5 py-1 text-xs">
                    <option value="">—</option>
                    {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </label>
                <label className="flex items-center gap-1 text-xs" style={{ color: "var(--rs-text-secondary)" }}>
                  <input type="checkbox" checked={form.spoiler} onChange={(e) => setForm({ ...form, spoiler: e.target.checked })} />
                  含剧透
                </label>
                <div className="flex-1" />
                <button onClick={() => setPreview((v) => !v)}
                  className="px-3 py-1.5 rounded-xl text-xs"
                  style={{ backgroundColor: preview ? "var(--rs-accent)" : "var(--rs-accent-soft)", color: preview ? "#1b1024" : "var(--rs-accent)" }}>
                  {preview ? "返回书写" : "预览"}
                </button>
                {editingId ? (
                  <button onClick={startNew} className="px-3 py-1.5 rounded-xl text-xs" style={{ color: "var(--rs-text-secondary)" }}>放弃编辑</button>
                ) : (
                  <button onClick={startNew} className="px-3 py-1.5 rounded-xl text-xs" style={{ color: "var(--rs-text-secondary)" }}>清空</button>
                )}
                <button onClick={submit} disabled={saving}
                  className="px-5 py-1.5 rounded-xl text-xs font-medium disabled:opacity-40"
                  style={{ backgroundColor: "var(--rs-accent)", color: "#1b1024" }}>
                  {saving ? "保存中…" : editingId ? "保存修改" : "发布"}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
