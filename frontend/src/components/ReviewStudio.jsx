// 书评工作室（Review Studio）——排版驱动的沉浸感
// 接入全局主题 token（ADR 0020：不再是独立的"第四套风格"）：细边框 + 克制阴影 +
// 主题底色，切换主题自然跟随。左参考区四标签 + 右编辑器结构不变。
// 正文：衬线字体 + ~720px 阅读宽度 + 1.78 行高（iA Writer / Bear 式写作空间）。
import React, { useEffect, useRef, useState } from "react";
import {
  fetchItemDetail, fetchItemReviews, fetchRelatedSources,
  createReview, updateReview, deleteReview, filePathToUrl,
} from "../api.js";
import { renderMarkdown } from "../markdown.js";
import { toast } from "../toast.js";
import { InfoTable, TagCapsule, itemInfoRows, ArchiveNo } from "./ui.jsx";

const STATUSES = ["想看", "在看", "看完", "搁置", "弃坑"];
const DEFAULT_FONT = 15;
const FONT_SIZES = [14, 15, 16, 18, 20];
const READ_WIDTH = 720;       // 舒适阅读宽度（px）
const CHAR_TARGET = 500;      // 字数进度条的目标字数
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

function sourceName(source) {
  return { bangumi: "Bangumi", moegirl: "萌娘百科", vndb: "VNDB" }[source] || source || "本地";
}

// 完整简介：优先 detail.description（raw_metadata 已下载全文），缺失时从
// reference_text 的"# 作品简介"小节提取（ADR 0026 用足已下载数据）
function introText(detail) {
  const desc = (detail?.description || "").trim();
  if (desc) return desc;
  const ref = detail?.reference_text || "";
  const m = ref.match(/^# 作品简介\s*\n+([\s\S]*?)(?=\n# |$)/m);
  return (m?.[1] || ref).trim() || "暂无简介。";
}

// 热度/评分分布替代数据（ADR 0026 实测三源无公开评论文本）
function SocialBlock({ source, social, rating }) {
  if (!social || Object.keys(social).length === 0) {
    return (
      <div className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
        暂无热度数据（可在详情弹层点「刷新资料」重新拉取）
      </div>
    );
  }
  const dist = social.rating_distribution;
  const total = social.rating_total || 0;
  return (
    <div className="space-y-2">
      {dist && (
        <div>
          <div className="flex items-baseline justify-between mb-1">
            <span className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
              评分分布{typeof social.rating_rank === "number" ? ` · 排第 ${social.rating_rank}` : ""}
              {total ? ` · ${total} 人评分` : ""}
            </span>
          </div>
          <div className="flex items-end gap-[3px] h-8">
            {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((s) => {
              const n = dist[s] || 0;
              const h = total ? Math.max((n / total) * 100, 2) : 2;
              return (
                <div key={s} className="flex-1 flex flex-col items-center gap-0.5" title={`${s}分：${n} 人`}>
                  <div className="w-full rounded-sm" style={{ height: `${h}%`, minHeight: 2, backgroundColor: "var(--accent)" }} />
                  <span className="text-[9px]" style={{ color: "var(--text-secondary)" }}>{s}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
      {social.collection && (
        <div className="text-[11px] leading-5">
          <span style={{ color: "var(--text-secondary)" }}>收藏 </span>
          {[["wish", "想看"], ["doing", "在看"], ["collect", "看过"], ["on_hold", "搁置"], ["dropped", "弃坑"]].map(([k, label]) => (
            <span key={k} className="mr-2" style={{ color: "var(--text)" }}>
              {label} {social.collection[k] ?? 0}
            </span>
          ))}
        </div>
      )}
      {social.votecount != null && (
        <div className="text-[11px]">
          <span style={{ color: "var(--text-secondary)" }}>评分 </span>
          <span style={{ color: "var(--text)" }}>{rating ?? "-"} / 10</span>
          <span className="ml-2" style={{ color: "var(--text-secondary)" }}>投票 {social.votecount} 人</span>
        </div>
      )}
      {social.page_info && (
        <div className="text-[11px] leading-5" style={{ color: "var(--text-secondary)" }}>
          页面长度 {social.page_info.length ?? "-"} 字节
          {social.page_info.touched ? ` · 最后编辑 ${String(social.page_info.touched).slice(0, 10)}` : ""}
          <div className="mt-0.5">（该数据源未公开评论/评分数据）</div>
        </div>
      )}
    </div>
  );
}

// 紧凑角色列表：行 = 名字 + 关系 + 可展开的小传
function CompactCharacters({ characters, expanded, onToggle }) {
  if (!characters || characters.length === 0) {
    return <div className="text-[11px]" style={{ color: "var(--text-secondary)" }}>暂无角色数据。</div>;
  }
  return (
    <div className="space-y-1">
      {characters.map((c, i) => {
        const key = c.id ?? i;
        const open = expanded.has(key);
        const summary = (c.summary || "").trim();
        return (
          <div key={key} className="rounded-lg px-2.5 py-1.5"
            style={{ backgroundColor: "rgba(128,128,128,0.05)", border: "1px solid var(--panel-border)" }}>
            <button type="button" onClick={() => onToggle(key)}
              className="w-full flex items-center gap-2 text-left">
              <span className="text-[11px] w-2 shrink-0" style={{ color: "var(--accent)" }}>{open ? "▾" : "▸"}</span>
              <span className="text-[13px] font-medium" style={{ color: "var(--text)" }}>{c.name || "?"}</span>
              {c.relation && <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>{c.relation}</span>}
            </button>
            {(open || !summary) && summary && (
              <div className="text-[12px] pl-4 mt-1 leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
                {summary}
                {Array.isArray(c.actors) && c.actors.length > 0 && (
                  <div className="mt-0.5">声优：{c.actors.join("、")}</div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function ReviewStudio({ item, onClose, refreshItems }) {
  const [detail, setDetail] = useState(null);
  const [reviews, setReviews] = useState([]);
  const [related, setRelated] = useState([]);        // 同作品跨来源兄弟条目（ADR 0026）
  const [sourceDetails, setSourceDetails] = useState({}); // itemId -> ItemDetailOut（懒加载）
  const [activeSourceId, setActiveSourceId] = useState(null);
  const [expandedChars, setExpandedChars] = useState(new Set());
  const [tab, setTab] = useState("overview");
  const [editingId, setEditingId] = useState(null);
  const [preview, setPreview] = useState(false);
  const [form, setForm] = useState({ ...emptyForm });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [closing, setClosing] = useState(false);
  const contentRef = useAutoGrow();

  useEffect(() => {
    fetchItemDetail(item.id).then(setDetail).catch(() => {});
    fetchRelatedSources(item.id).then(setRelated).catch(() => {});
    setActiveSourceId(item.id);
    loadReviews();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  // 切换来源时懒加载该来源条目的详情（当前条目已加载，直接复用）
  function selectSource(srcId) {
    setActiveSourceId(srcId);
    setExpandedChars(new Set());
    if (srcId === item.id) return;
    if (sourceDetails[srcId]) return;
    fetchItemDetail(srcId).then((d) => {
      setSourceDetails((prev) => ({ ...prev, [srcId]: d }));
    }).catch((e) => toast.error(e.message));
  }

  const activeDetail = activeSourceId === item.id ? detail : (sourceDetails[activeSourceId] || null);
  const activeRelated = related.find((r) => r.id === activeSourceId);

  function loadReviews() {
    fetchItemReviews(item.id).then(setReviews).catch((e) => setError(e.message));
  }

  // 退出：先走 0.18s 淡出过渡再真正关闭（纯 CSS transition）
  function handleClose() {
    if (closing) return;
    setClosing(true);
    setTimeout(onClose, 180);
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
  const charCount = form.content.replace(/\s/g, "").length;
  const charPct = Math.min(Math.round((charCount / CHAR_TARGET) * 100), 100);

  return (
    <div className={`review-studio fixed inset-0 z-50 overflow-hidden${closing ? " closing" : ""}`}>
      {cover && <div className="rs-bg" style={{ backgroundImage: `url(${cover})` }} />}
      <div className="relative h-full w-full flex flex-col" style={{ padding: 18 }}>
        {/* 顶部栏 */}
        <div className="rs-panel flex items-center gap-3 px-4 py-2.5 mb-3">
          <button onClick={handleClose} className="text-sm px-2 py-1 rounded-lg hover:opacity-75"
            style={{ color: "var(--text-secondary)" }}>← 返回</button>
          <div className="min-w-0">
            <div className="text-sm font-medium truncate" style={{ color: "var(--text)" }}>
              {detail?.title || item.title}
            </div>
            <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
              {detail?.source || "local"}
              {detail?.rating != null && <> · 大众 ★{detail.rating}</>}
              {myAvg != null && <> · 我的平均 ★{myAvg}（{reviews.length} 条）</>}
            </div>
          </div>
          <div style={{ flex: 1 }} />
          <button onClick={handleClose} className="text-sm px-2 py-1 rounded-lg hover:opacity-75"
            style={{ color: "var(--text-secondary)" }}>✕</button>
        </div>

        <div className="grid gap-3 flex-1 min-h-0" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.15fr)" }}>
          {/* 左：参考区 */}
          <div className="rs-panel flex flex-col min-h-0">
            <div className="flex gap-1 px-3 pt-3 pb-2 border-b" style={{ borderColor: "var(--panel-border)" }}>
              {TABS.map((t) => (
                <button key={t.key} onClick={() => setTab(t.key)}
                  className={`rs-tab ${tab === t.key ? "on" : ""}`}>{t.label}</button>
              ))}
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {tab === "overview" && (
                <>
                  {/* 多来源切换（ADR 0026）：当前条目 + 同作品其它来源的收藏 */}
                  {related.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {[{ id: item.id, source: detail?.source, title: item.title }, ...related].map((r) => {
                        const active = activeSourceId === r.id;
                        return (
                          <button key={r.id} type="button" onClick={() => selectSource(r.id)}
                            className="px-2 py-1 rounded-lg text-[11px]"
                            style={{ backgroundColor: active ? "var(--accent)" : "var(--accent-soft)",
                              color: active ? "#fff" : "var(--accent)" }}>
                            {sourceName(r.source)}
                          </button>
                        );
                      })}
                    </div>
                  )}
                  {!activeDetail && (
                    <div className="text-sm py-6 text-center" style={{ color: "var(--text-secondary)" }}>
                      {activeSourceId !== item.id ? "加载该来源资料…" : "暂无资料"}
                    </div>
                  )}
                  {activeDetail && (
                    <>
                      <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
                        <div className="flex items-center gap-2 mb-2">
                          <b style={{ color: "var(--text)" }}>简介</b>
                          {activeRelated && <span className="text-[10px]" style={{ color: "var(--text-secondary)" }}>来自 {sourceName(activeRelated.source)}</span>}
                          {activeDetail.rating != null && (
                            <span className="text-[11px] ml-auto shrink-0" style={{ color: "var(--amber, #ffc24b)" }}>★{activeDetail.rating}</span>
                          )}
                        </div>
                        <div className="whitespace-pre-wrap leading-relaxed" style={{ fontSize: 13 }}>
                          {introText(activeDetail)}
                        </div>
                      </div>
                      {/* 基本信息：属性表格（Playnite 式，ADR 0029） */}
                      {itemInfoRows(activeDetail).length > 0 && (
                        <div>
                          <div className="text-[11px] mb-1.5" style={{ color: "var(--text-secondary)" }}>基本信息</div>
                          <InfoTable rows={itemInfoRows(activeDetail)} />
                        </div>
                      )}
                      {(activeDetail.tags || []).length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {(activeDetail.tags || []).map((t) => <TagCapsule key={t} text={t} />)}
                        </div>
                      )}
                      {/* 热度/评分分布替代数据（ADR 0026） */}
                      <div>
                        <div className="text-[11px] mb-1.5" style={{ color: "var(--text-secondary)" }}>热度 / 评分分布</div>
                        <SocialBlock source={activeDetail.source} social={activeDetail.social} rating={activeDetail.rating} />
                      </div>
                      {/* 紧凑角色列表（完整资料已下载，Overview 用足） */}
                      <div>
                        <div className="text-[11px] mb-1.5" style={{ color: "var(--text-secondary)" }}>角色（{activeDetail.characters?.length || 0}）</div>
                        <CompactCharacters
                          characters={activeDetail.characters}
                          expanded={expandedChars}
                          onToggle={(k) => setExpandedChars((prev) => {
                            const next = new Set(prev);
                            if (next.has(k)) next.delete(k); else next.add(k);
                            return next;
                          })}
                        />
                      </div>
                    </>
                  )}
                </>
              )}
              {tab === "records" && (
                <>
                  {reviews.length === 0 && (
                    <div className="text-sm py-8 text-center" style={{ color: "var(--text-secondary)" }}>
                      还没有书评 · 在右侧开始书写
                    </div>
                  )}
                  {reviews.map((r, i) => (
                    <div key={r.id} className="rounded-xl p-3"
                      style={{ backgroundColor: "rgba(128,128,128,0.05)", border: "1px solid var(--panel-border)" }}>
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="flex items-center gap-2">
                          <ArchiveNo color="muted">{String(i + 1).padStart(2, "0")}</ArchiveNo>
                          <span className="text-sm font-medium" style={{ color: "var(--text)" }}>{r.title || "读后感"}</span>
                          {r.rating != null && <span className="text-xs" style={{ color: "var(--accent)" }}>★{r.rating}</span>}
                          {r.status && <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>{r.status}</span>}
                        </div>
                        <div className="flex items-center gap-2">
                          <button onClick={() => startEdit(r)} className="text-[11px]" style={{ color: "var(--text-secondary)" }}>编辑</button>
                          <button onClick={() => remove(r)} className="text-[11px]" style={{ color: "var(--danger)" }}>删除</button>
                        </div>
                      </div>
                      {r.spoiler ? (
                        <button onClick={() => { }}
                          className="text-xs px-2 py-1 rounded-full"
                          style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
                          含剧透 · 在编辑器查看
                        </button>
                      ) : (
                        <div className="doc rs-prose" style={{ fontSize: `${r.font_size || DEFAULT_FONT}px` }}
                          dangerouslySetInnerHTML={{ __html: renderMarkdown(r.content) }} />
                      )}
                    </div>
                  ))}
                </>
              )}
              {tab === "archive" && (
                <>
                  <div className="text-xs" style={{ color: "var(--text-secondary)" }}>角色资料</div>
                  {(detail?.characters || []).length === 0 && (
                    <div className="text-sm" style={{ color: "var(--text-secondary)" }}>暂无角色数据。</div>
                  )}
                  <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(92px, 1fr))" }}>
                    {(detail?.characters || []).map((c, i) => (
                      <div key={c.id ?? i} className="rounded-xl overflow-hidden text-center"
                        style={{ backgroundColor: "rgba(128,128,128,0.05)", border: "1px solid var(--panel-border)" }}>
                        {c.image_url ? (
                          <img src={c.image_url} alt="" className="w-full object-cover" style={{ aspectRatio: "3/4" }}
                            onError={(e) => { e.target.style.display = "none"; }} />
                        ) : (
                          <div className="w-full flex items-center justify-center" style={{ aspectRatio: "3/4", backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
                            {(c.name || "?").charAt(0)}
                          </div>
                        )}
                        <div className="px-1 py-1">
                          <div className="text-[11px] truncate" style={{ color: "var(--text)" }}>{c.name}</div>
                          {c.relation && <div className="text-[10px]" style={{ color: "var(--text-secondary)" }}>{c.relation}</div>}
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
              {tab === "memories" && (
                <>
                  <div className="text-xs" style={{ color: "var(--text-secondary)" }}>书写时间线</div>
                  {reviews.length === 0 && (
                    <div className="text-sm" style={{ color: "var(--text-secondary)" }}>还没有留下记忆。</div>
                  )}
                  {[...reviews].sort((a, b) => (a.created_at > b.created_at ? 1 : -1)).map((r) => (
                    <div key={r.id} className="flex items-center gap-3 text-sm" style={{ color: "var(--text-secondary)" }}>
                      <span className="text-[11px] w-28 shrink-0" style={{ color: "var(--text)" }}>{fmtDate(r.created_at)}</span>
                      <span>{r.status || "—"}</span>
                      {r.rating != null && <span style={{ color: "var(--accent)" }}>★{r.rating}</span>}
                      <span className="truncate">{r.title || "读后感"}</span>
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>

          {/* 右：编辑器 */}
          <div className="rs-panel relative flex flex-col min-h-0">
            <div className="px-5 pt-4 pb-2" style={{ maxWidth: READ_WIDTH, margin: "0 auto", width: "100%" }}>
              <input
                placeholder="标题（可选）"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                className="w-full bg-transparent outline-none font-semibold"
                style={{ fontSize: 22, color: "var(--text)", borderBottom: "1px solid var(--panel-border)", paddingBottom: 10, marginBottom: 12 }}
              />
              <div className="flex items-center gap-1 flex-wrap pb-2" style={{ borderBottom: "1px solid var(--panel-border)" }}>
                <select
                  value={form.font_size}
                  onChange={(e) => { const v = Number(e.target.value); setForm({ ...form, font_size: v }); requestAnimationFrame(contentRef.grow); }}
                  title="正文字号"
                  className="rs-field px-1.5 py-1 text-xs mr-1"
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
                  {charCount} 字
                </span>
              </div>
            </div>
            {/* 字数进度：纤细强调色渐变条（本轮唯一克制点缀） */}
            <div className="px-5" style={{ maxWidth: READ_WIDTH, margin: "0 auto", width: "100%" }}>
              <div className="rs-progress-track mb-1"><div className="rs-progress-fill" style={{ width: `${charPct}%` }} /></div>
            </div>
            <div className="flex-1 overflow-y-auto px-5 py-3">
              <div className="rs-prose" style={{ maxWidth: READ_WIDTH, margin: "0 auto", width: "100%" }}>
                {preview ? (
                  <div className="doc rs-prose rounded-xl px-5 py-4"
                    style={{ backgroundColor: "rgba(128,128,128,0.05)", border: "1px solid var(--panel-border)", fontSize: `${form.font_size}px`, minHeight: "48vh" }}
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(form.content) || "<p style='color:var(--text-secondary)'>（暂无内容）</p>" }} />
                ) : (
                  <textarea
                    ref={contentRef.ref}
                    placeholder={"写下你的感想…\n\n支持 Markdown：**加粗**、## 小标题、- 列表、> 引用；内容会参与知识库检索。"}
                    value={form.content}
                    onChange={(e) => { setForm({ ...form, content: e.target.value }); contentRef.grow(); }}
                    className="w-full bg-transparent outline-none resize-none"
                    style={{ fontSize: `${form.font_size}px`, lineHeight: 1.78, color: "var(--text)", minHeight: "48vh" }}
                  />
                )}
              </div>
            </div>
            {/* 浮动引用卡 */}
            <div className="rs-quote">
              <div className="text-[10px] mb-1" style={{ color: "var(--accent)" }}>引用卡</div>
              <div className="line-clamp-3">“{quote || "在正文里用 > 写一句引用，会浮现到这里" }”</div>
            </div>
            {/* 底部：评分/状态/操作 */}
            <div className="px-5 py-3 border-t" style={{ borderColor: "var(--panel-border)" }}>
              {error && <p className="text-xs mb-2" style={{ color: "var(--danger)" }}>{error}</p>}
              <div className="flex items-center gap-3 flex-wrap">
                <label className="flex items-center gap-1 text-xs" style={{ color: "var(--text-secondary)" }}>
                  评分
                  <select value={form.rating} onChange={(e) => setForm({ ...form, rating: e.target.value })}
                    className="rs-field px-1.5 py-1 text-xs">
                    <option value="">—</option>
                    {[...Array(11)].map((_, i) => <option key={i} value={i}>{i}</option>)}
                  </select>
                </label>
                <label className="flex items-center gap-1 text-xs" style={{ color: "var(--text-secondary)" }}>
                  状态
                  <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}
                    className="rs-field px-1.5 py-1 text-xs">
                    <option value="">—</option>
                    {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </label>
                <label className="flex items-center gap-1 text-xs" style={{ color: "var(--text-secondary)" }}>
                  <input type="checkbox" checked={form.spoiler} onChange={(e) => setForm({ ...form, spoiler: e.target.checked })} />
                  含剧透
                </label>
                <div className="flex-1" />
                <button onClick={() => setPreview((v) => !v)}
                  className="px-3 py-1.5 rounded-xl text-xs"
                  style={{ backgroundColor: preview ? "var(--accent)" : "var(--accent-soft)", color: preview ? "#fff" : "var(--accent)" }}>
                  {preview ? "返回书写" : "预览"}
                </button>
                {editingId ? (
                  <button onClick={startNew} className="px-3 py-1.5 rounded-xl text-xs" style={{ color: "var(--text-secondary)" }}>放弃编辑</button>
                ) : (
                  <button onClick={startNew} className="px-3 py-1.5 rounded-xl text-xs" style={{ color: "var(--text-secondary)" }}>清空</button>
                )}
                <button onClick={submit} disabled={saving}
                  className="px-5 py-1.5 rounded-xl text-xs font-medium disabled:opacity-40"
                  style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
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
