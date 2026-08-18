// 主从视图的"从"面板（ADR 0029）：点击左侧列表条目，这里**立即**更新详情。
// 复用 InfoTable（属性表格）+ TagCapsule（标签胶囊）+ 完整简介 + 角色紧凑列表，
// 独立滚动，不跳转/不弹层。
// ADR 0034：封面动态取色氛围——封面主色调作为表面色之上的柔和角部光晕（box-shadow
// 平滑过渡），不覆盖文字/按钮；浅色主题克制、深色稍明显（--ambient-alpha）。
// Phase B（ADR 0042）：双栏结构——"外部世界"（世界如何描述它）与"我的记录"
// （我如何理解它，含 Memory 记忆时间轴）。
// Phase 3-1（ADR 0075）：ItemDetailPanel 成为**统一 Work Detail 内容基底**。
// - Classic（主从/网格/书架/角色墙/回廊/关系厅）、Mobile Detail Scene 共用同一内容；
// - 新增外部未收藏模式：`externalDetail`（无 itemId）只呈现作品本身 + 这个世界 + 外部操作
//   （收藏入库/安利卡/刷新），回调由调用方传入（Panel 不承担新后端业务）；
// - `refreshKey` 用于"刷新资料"后重取详情。
import React, { useEffect, useRef, useState } from "react";
import { fetchItemDetail, fetchItemReviews, fetchItemMemories, filePathToUrl, updateWorkColumns, updateCollection, createDirectMemory } from "../api.js";
import { TagCapsule, itemInfoRows, WORK_TYPES, WORK_TYPE_LABEL, COLLECTION_STATUSES, MEMORY_EMOTIONS, ProviderBadge, PROVIDER_LABELS } from "./ui.jsx";
import { extractPalette } from "../ambient.js";
import MemoryTimeline from "./MemoryTimeline.jsx";
import { buildEncounterEvents } from "../encounter.js";

function introText(detail) {
  const desc = (detail?.description || "").trim();
  if (desc) return desc;
  const ref = detail?.reference_text || "";
  const m = ref.match(/^# 作品简介\s*\n+([\s\S]*?)(?=\n# |$)/m);
  return (m?.[1] || ref).trim() || "暂无简介。";
}

// 相遇纪事日期：YYYY.MM.DD（mono 小字；事件时间为 event.occurredAt 的事实时间）
function encounterDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (!Number.isNaN(d.getTime())) {
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())}`;
  }
  return String(iso).slice(0, 10).replace(/-/g, ".");
}

// 氛围强度：读 --ambient-alpha（浅色 0.16-0.18，深色 0.30）；jsdom/未定义时回退 0.16
function ambientAlpha() {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue("--ambient-alpha").trim();
    const n = parseFloat(v);
    if (Number.isFinite(n)) return n;
  } catch { /* ignore */ }
  return 0.16;
}

export default function ItemDetailPanel({
  itemId, className = "",
  externalDetail = null, refreshKey = 0,
  onSaveDetail, onShareDetail, onRefreshDetail, onOpenReview,
  composerFocusTick = 0,
  onOpenRelated, // Phase 12-D：点击本地关系作品（target_item_id）
  onOpenPerson, // Phase 13-B：点击角色 / Staff → 人物面板
}) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [palette, setPalette] = useState(null); // 封面主色调 {primary, secondary}

  useEffect(() => {
    if (itemId == null) { setDetail(null); setError(""); return; }
    let cancelled = false;
    setLoading(true);
    setError("");
    fetchItemDetail(itemId)
      .then((d) => { if (!cancelled) setDetail(d); })
      .catch((e) => { if (!cancelled) { setError(e.message); setDetail(null); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [itemId, refreshKey]);

  // ADR 0034：详情变化时从封面提取主色调（缓存于 ambient 模块；本地缓存封面优先，
  // 同源无 taint）。加载中保持旧氛围，新色就绪后经 box-shadow transition 平滑过渡。
  useEffect(() => {
    if (!detail && !externalDetail) return;
    let cancelled = false;
    const src = externalDetail || detail;
    const coverSrc = filePathToUrl(src?.file_path) || src?.image_url || "";
    if (!coverSrc) { setPalette(null); return; }
    extractPalette(coverSrc).then((p) => { if (!cancelled) setPalette(p); });
    return () => { cancelled = true; };
  }, [detail, externalDetail]);

  // P1（ADR 0045）：外部作品可在"外部世界"区内联修正作品类型（回填只在 NULL 时写，
  // 用户值不被覆盖）。Hook 放在所有条件返回之前，遵守 Rules of Hooks。
  const [workType, setWorkType] = useState("");
  const [workSaving, setWorkSaving] = useState(false);
  useEffect(() => { if (detail) setWorkType(detail.work_type || ""); }, [detail?.work_type]);
  function changeWorkType(e) {
    const v = e.target.value;
    setWorkType(v);
    setWorkSaving(true);
    updateWorkColumns(itemId, { work_type: v })
      .then((fresh) => setDetail((d) => (d ? { ...d, work_type: fresh.work_type } : d)))
      .catch(() => setWorkType((detail && detail.work_type) || ""))
      .finally(() => setWorkSaving(false));
  }

  // P2（ADR 0046）：我的记录区内联编辑收藏状态/是否喜欢
  const [colStatus, setColStatus] = useState("");
  const [favorite, setFavorite] = useState(false);
  const [colSaving, setColSaving] = useState(false);
  useEffect(() => {
    if (!detail) return;
    setColStatus(detail.collection_status || "");
    setFavorite(!!detail.favorite);
  }, [detail?.collection_status, detail?.favorite]);
  function patchCollection(patch) {
    setColSaving(true);
    updateCollection(itemId, patch)
      .then((fresh) => setDetail((d) => (d ? {
        ...d, collection_status: fresh.collection_status, favorite: fresh.favorite,
      } : d)))
      .catch(() => { if (detail) { setColStatus(detail.collection_status || ""); setFavorite(!!detail.favorite); } })
      .finally(() => setColSaving(false));
  }

  // P3（ADR 0047）：轻量记录 / 里程碑 composer（一句话 + 情绪 + 可选附图）
  const [draft, setDraft] = useState("");
  const [draftEmotion, setDraftEmotion] = useState("");
  const [draftFile, setDraftFile] = useState(null);
  const [recording, setRecording] = useState(false);
  const [timelineRefresh, setTimelineRefresh] = useState(0);
  const fileInputRef = useRef(null);
  const composerRef = useRef(null); // Phase 10-1-A-2：收藏后引导聚焦「我的记忆」输入框
  useEffect(() => {
    if (composerFocusTick > 0 && composerRef.current) composerRef.current.focus?.();
  }, [composerFocusTick]);

  // Phase 4-3：提交反馈——安静一行（ok 短暂 / error 持续到下次操作 / busy 进行中）
  const [feedback, setFeedback] = useState(null); // { kind: "busy"|"ok"|"error", text } | null
  const feedbackTimer = useRef(null);
  const submittingRef = useRef(false);
  function showFeedback(kind, text) {
    if (feedbackTimer.current) clearTimeout(feedbackTimer.current);
    setFeedback({ kind, text });
    if (kind === "ok") {
      feedbackTimer.current = setTimeout(() => setFeedback(null), 2500);
    }
  }
  useEffect(() => () => { if (feedbackTimer.current) clearTimeout(feedbackTimer.current); }, []);

  // Phase 3-2-C-1（ADR 0076）：相遇纪事数据——统一在此取 reviews/memories，
  // 同一份 memories 同时供给 MemoryTimeline（避免重复请求）。
  const [reviews, setReviews] = useState([]);
  const [memories, setMemories] = useState([]);
  const [memReady, setMemReady] = useState(false); // 记录数据就绪（防空态引导闪烁）
  useEffect(() => {
    if (itemId == null) { setReviews([]); setMemories([]); setMemReady(false); return; }
    let cancelled = false;
    setMemReady(false);
    Promise.all([
      fetchItemReviews(itemId).then((r) => (Array.isArray(r) ? r : [])).catch(() => []),
      fetchItemMemories(itemId).then((m) => (Array.isArray(m) ? m : [])).catch(() => []),
    ]).then(([r, m]) => {
      if (cancelled) return;
      setReviews(r); setMemories(m); setMemReady(true);
    });
    return () => { cancelled = true; };
  }, [itemId, timelineRefresh]);

  async function submitDirect(sourceType, text) {
    if (submittingRef.current) return; // 防重复提交（含渲染前双击）
    submittingRef.current = true;
    setRecording(true);
    showFeedback("busy", "正在记录…");
    try {
      await createDirectMemory(itemId, {
        summary: text, source_type: sourceType,
        emotion: draftEmotion, file: sourceType === "text" ? draftFile : null,
      });
      setDraft(""); setDraftEmotion(""); setDraftFile(null);
      setTimelineRefresh((k) => k + 1);
      showFeedback("ok", "已留下这一刻");
    } catch (err) {
      // 失败：保留输入便于重试；安静可读的失败反馈
      showFeedback("error", (err && err.message) || "记录失败，请重试");
    } finally {
      submittingRef.current = false;
      setRecording(false);
    }
  }

  // Phase 3-1：外部未收藏详情（externalDetail）跳过取数守卫；已收藏走 detail（自取）
  const externalMode = !!externalDetail;
  if (!externalMode) {
    if (itemId == null) {
      return (
        <div className={"flex items-center justify-center text-sm " + className}
          style={{ color: "var(--text-secondary)" }}>
          从左侧列表选择一条资料，详情会显示在这里。
        </div>
      );
    }
    if (loading) {
      return <div className={"flex items-center justify-center text-sm " + className} style={{ color: "var(--text-secondary)" }}>加载详情…</div>;
    }
    if (error || !detail) {
      return <div className={"flex items-center justify-center text-sm " + className} style={{ color: "var(--danger)" }}>{error || "加载失败"}</div>;
    }
  }

  const data = externalDetail || detail;
  const cover = data.image_url || filePathToUrl(data?.file_path) || "";
  // Phase 3-3：编目去重——数据源/大众评分/我的评分已由「作品本身」身份行与「我与它」承担，
  // 不在此世界的 quiet catalog 中重复（信息不丢失，仅消除三处重复）。
  const WORLD_CATALOG_EXCLUDE = new Set(["数据源", "大众评分", "我的评分"]);
  const rows = itemInfoRows(data).filter((r) => !WORLD_CATALOG_EXCLUDE.has(r.label));
  const tags = data.tags || [];

  // Phase 3-2-C-1：相遇纪事事件（仅已收藏；由 buildEncounterEvents 唯一构造，不重复推导）
  const encounterEvents = detail ? buildEncounterEvents({
    collection: { added_at: detail.collected_at, status: detail.collection_status, favorite: detail.favorite },
    reviews,
    memories,
  }) : [];

  // 氛围光晕（box-shadow 可平滑过渡；无主色时透明，回退主题表面色）
  const alpha = ambientAlpha();
  const p = palette && palette.primary;
  const glowShadow = p
    ? `0 0 120px 30px rgba(${p.r},${p.g},${p.b},${alpha}), 0 0 52px 12px rgba(${p.r},${p.g},${p.b},${alpha * 0.6})`
    : "0 0 0px 0px transparent, 0 0 0px 0px transparent";

  return (
    <div className={(className + " relative overflow-hidden").trim()}>
      {/* 氛围光晕层：角部柔和光晕，不参与交互、不覆盖文字 */}
      <div aria-hidden data-testid="ambient-glow" className="absolute pointer-events-none"
        style={{
          width: 260, height: 260, borderRadius: "50%", right: -80, top: -80,
          boxShadow: glowShadow, transition: "box-shadow 0.5s ease", zIndex: 0,
        }} />
      <div className="relative" style={{ zIndex: 1 }}>
        {/* 作品本身（Phase 3-2-A）：封面为第一视觉锚点——像桌上的一本书；
            标题 serif；NO./来源/评分收敛为 mono 编目行，不再胶囊堆叠 */}
        <div className="flex gap-4 mb-6 items-start">
          {cover ? (
            <div className="wd-cover shrink-0" style={{ width: 128 }}>
              <img src={cover} alt="" style={{ aspectRatio: "3/4" }}
                onError={(e) => { e.target.style.display = "none"; }} />
            </div>
          ) : null}
          <div className="min-w-0">
            <h2 className="tsm-heading leading-tight" style={{ color: "var(--text)", fontSize: 24, fontWeight: 600 }}>{data.title}</h2>
            {data.id != null && (
              <div className="wd-meta mt-1.5">NO. {String(data.id).padStart(4, "0")}</div>
            )}
            {data.alternative_title ? (
              <div className="wd-meta mt-1" style={{ fontSize: 13, letterSpacing: "0.04em" }}>{data.alternative_title}</div>
            ) : null}
            {/* Phase 11-D：年份 · 类型 · 状态 · 集数（空字段隐藏） */}
            {[
              data.release_date ? String(data.release_date).slice(0, 4) : null,
              data.work_type ? WORK_TYPE_LABEL[data.work_type] : null,
              data.status || null,
              data.episodes != null ? `${data.episodes} 集` : null,
            ].filter(Boolean).length > 0 && (
              <div className="wd-meta mt-1.5">
                {[data.release_date ? String(data.release_date).slice(0, 4) : null,
                  data.work_type ? WORK_TYPE_LABEL[data.work_type] : null,
                  data.status || null,
                  data.episodes != null ? `${data.episodes} 集` : null].filter(Boolean).join(" · ")}
              </div>
            )}
            <div className="wd-meta mt-1">
              {data.rating != null && <span>大众 ★{data.rating}</span>}
              {data.my_rating != null && <span>{data.rating != null ? " · " : ""}我的平均 ★{data.my_rating}</span>}
            </div>
            {(data.sources && data.sources.length > 0) ? (
              <div className="mt-2"><ProviderBadge source={data.source} sources={data.sources} count /></div>
            ) : null}
          </div>
        </div>

        {/* 这个世界（Phase 3-2-A）：作品自身是什么——简介优先（阅读），编目为辅助（非表格中心），
            标签轻量索引，角色是作品世界的一部分 */}
        <section>
          <div className="flex items-baseline justify-between gap-2 flex-wrap">
            <div className="flex items-baseline gap-3">
              <h3 className="wd-chapter-title">这个世界</h3>
              <span className="wd-meta" style={{ fontSize: 10, letterSpacing: "0.2em" }}>WORLD</span>
            </div>
            {!externalMode && detail.source !== "local" && (
              <select value={workType} onChange={changeWorkType} title="作品类型（可手动修正）"
                disabled={workSaving}
                className="px-2 py-1 text-[11px] outline-none"
                style={{ backgroundColor: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)", borderRadius: "var(--radius-control)" }}>
                <option value="">未分类</option>
                {WORK_TYPES.map((t) => <option key={t} value={t}>{WORK_TYPE_LABEL[t]}</option>)}
              </select>
            )}
          </div>
          <div className="wd-chapter-rule" />

          <div className="wd-intro">{introText(data)}</div>

          {rows.length > 0 && (
            <div className="wd-catalog">
              {rows.map((r) => (
                <div key={r.label} className="wd-catalog-row">
                  <span className="wd-catalog-label">{r.label}</span>
                  <span className="wd-catalog-value">{r.value}</span>
                </div>
              ))}
            </div>
          )}

          {data.background && (
            <div style={{ marginTop: 10, borderRadius: "var(--radius-cover)", overflow: "hidden", height: 72, background: "var(--card-thumb)" }}>
              <img src={data.background} alt="" loading="lazy"
                onError={(e) => { e.target.style.visibility = "hidden"; }}
                style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
            </div>
          )}

          {/* Phase 11-A/B + 12-C：丰富媒体元数据（可选字段，空则隐藏） */}
          {(data.genres?.length || data.themes?.length || data.demographics?.length || data.status
            || data.episodes != null || data.duration || data.season || data.studios?.length) && (
            <div className="wd-catalog" style={{ marginTop: 10 }}>
              {(data.genres?.length || data.themes?.length || data.demographics?.length) ? (
                <div className="wd-catalog-row"><span className="wd-catalog-label">题材</span>
                  <span className="wd-catalog-value">{[...(data.genres || []), ...(data.themes || []), ...(data.demographics || [])].join(" / ")}</span></div>
              ) : null}
              {data.status ? (
                <div className="wd-catalog-row"><span className="wd-catalog-label">状态</span><span className="wd-catalog-value">{data.status}</span></div>
              ) : null}
              {data.episodes != null ? (
                <div className="wd-catalog-row"><span className="wd-catalog-label">集数</span><span className="wd-catalog-value">{data.episodes}</span></div>
              ) : null}
              {data.duration ? (
                <div className="wd-catalog-row"><span className="wd-catalog-label">时长</span><span className="wd-catalog-value">{data.duration}</span></div>
              ) : null}
              {data.season ? (
                <div className="wd-catalog-row"><span className="wd-catalog-label">季度</span><span className="wd-catalog-value">{data.season}</span></div>
              ) : null}
              {data.studios?.length ? (
                <div className="wd-catalog-row"><span className="wd-catalog-label">制作</span><span className="wd-catalog-value">{data.studios.join(" / ")}</span></div>
              ) : null}
            </div>
          )}
          {/* Phase 12-D：Staff 列表（按 credit_order 排序，同人合并角色徽标） */}
          {(data.staff || []).length > 0 && (() => {
            const merged = [];
            for (const s of (data.staff || [])) {
              const prev = merged.find((x) => x.name === s.name);
              if (prev) { prev.roles.push(s.role); }
              else { merged.push({ name: s.name, roles: s.role ? [s.role] : [], source: s.source, external_id: s.external_id }); }
            }
            return (
              <div className="wd-chars">
                <div className="wd-chars-title">Staff · {data.staff.length}</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {merged.slice(0, 24).map((s, i) => (
                    <div key={i} onClick={onOpenPerson && s.source && s.external_id
                      ? () => onOpenPerson({ type: "staff", source: s.source, external_id: String(s.external_id), name: s.name }) : undefined}
                      title={onOpenPerson && s.source && s.external_id ? `查看「${s.name}」的相关作品` : undefined}
                      style={{ display: "flex", alignItems: "baseline", gap: 8, fontSize: 11, padding: "2px 4px", borderRadius: "var(--radius-control)", cursor: onOpenPerson && s.source && s.external_id ? "pointer" : "default" }}>
                      <span className="tsm-tag" style={{ flexShrink: 0, fontSize: 10, padding: "0 6px", borderRadius: "var(--radius-control)" }}>
                        {s.roles.length ? s.roles.join(" / ") : "制作"}
                      </span>
                      <span style={{ color: "var(--text)", fontWeight: 500 }}>{s.name}</span>
                      {s.source ? (
                        <span style={{ color: "var(--ink-2)", fontSize: 10, marginLeft: "auto", flexShrink: 0 }}>{PROVIDER_LABELS[s.source] || s.source}</span>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}
          {/* Phase 12-D：Relations 分组 + 可点击导航（本地→onOpenRelated / 外部→external_url） */}
          {(data.relations || []).length > 0 && (() => {
            const labels = { prequel: "前作", sequel: "后作", side_story: "外传", spin_off: "衍生", adaptation: "改编", alternative: "相关", parent_story: "主线", other: "其他" };
            const groups = {};
            for (const r of (data.relations || [])) {
              const key = labels[r.relation_type] || "其他";
              (groups[key] = groups[key] || []).push(r);
            }
            const renderRow = (r, i) => {
              // Phase 13-E：仅当本地关系确实能打开（target_item_id 存在）才渲染可点击按钮；
              // MediaEntry 存在但 Item 已删除（target_item_id null）时回退外部链接，避免死按钮。
              const isLocal = r.is_local || r.target_media_id != null;
              const clickableLocal = isLocal && r.target_item_id != null;
              const url = r.external_url;
              const inner = (
                <span style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 6, overflow: "hidden" }}>
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text)" }}>{r.title}</span>
                  <ProviderBadge source={r.source} />
                  {isLocal ? <span className="tsm-tag" style={{ fontSize: 9, padding: "0 5px", flexShrink: 0 }}>本地</span> : null}
                </span>
              );
              const base = { display: "flex", alignItems: "center", gap: 6, width: "100%", textAlign: "left", padding: "4px 6px", borderRadius: "var(--radius-control)", fontSize: 12, border: "none", background: "transparent" };
              if (clickableLocal && onOpenRelated) {
                return <button key={i} onClick={() => onOpenRelated(r.target_item_id)} style={{ ...base, cursor: "pointer" }}>{inner}</button>;
              }
              return <a key={i} href={url || undefined} target="_blank" rel="noreferrer"
                style={{ ...base, textDecoration: "none", color: "var(--text)", cursor: url ? "pointer" : "default" }}>{inner}</a>;
            };
            return (
              <div className="wd-chars">
                <div className="wd-chars-title">Relations · {data.relations.length}</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {Object.entries(groups).map(([label, list]) => (
                    <div key={label}>
                      <div className="wd-chars-title" style={{ marginTop: 4, color: "var(--accent)" }}>{label}</div>
                      {list.slice(0, 6).map(renderRow)}
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}
          {/* Phase 11-D：来源（MediaSource）——provider / external_id / 外部链接 */}
          {(data.sources || []).length > 0 && (
            <div className="wd-chars">
              <div className="wd-chars-title">来源 · {data.sources.length}</div>
              <div className="flex flex-wrap gap-1.5">
                {(data.sources || []).map((s, i) => (
                  <a key={i} href={s.external_url || undefined} target="_blank" rel="noreferrer"
                    className="tsm-tag"
                    style={{ fontSize: 11, padding: "2px 8px", borderRadius: "var(--radius-control)", textDecoration: "none", cursor: s.external_url ? "pointer" : "default" }}>
                    {PROVIDER_LABELS[s.source] || s.source}
                    {s.external_id ? ` · ${s.external_id}` : ""}
                  </a>
                ))}
              </div>
            </div>
          )}

          {/* Phase 12-C：外部链接（仅展示合法 http/https） */}
          {(data.external_links || []).length > 0 && (
            <div className="wd-chars">
              <div className="wd-chars-title">外部链接</div>
              <div className="flex flex-wrap gap-1.5">
                {(data.external_links || []).slice(0, 8).map((l, i) => {
                  const u = typeof l === "string" ? l : l.url;
                  if (!u || !/^https?:\/\//.test(u)) return null;
                  return (
                    <a key={i} href={u} target="_blank" rel="noreferrer"
                      className="tsm-tag"
                      style={{ fontSize: 11, padding: "2px 8px", borderRadius: "var(--radius-control)", textDecoration: "none", cursor: "pointer" }}>
                      {l.label || u}
                    </a>
                  );
                })}
              </div>
            </div>
          )}

          {tags.length > 0 && (
            <div className="wd-tags">
              {tags.map((t) => <TagCapsule key={t} text={t} />)}
            </div>
          )}

          {/* Phase 12-D：角色紧凑卡片（头像/占位 + 名称 + 关系 + CV，空字段隐藏） */}
          {(data.characters || []).length > 0 && (
            <div className="wd-chars">
              <div className="wd-chars-title">角色 · {data.characters.length}</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 8 }}>
                {(data.characters || []).slice(0, 12).map((c) => (
                  <div key={c.id ?? c.name}
                    onClick={onOpenPerson && c.id != null && c.id !== ""
                      ? () => onOpenPerson({ type: "character", source: data.source, external_id: String(c.id), name: c.name }) : undefined}
                    title={onOpenPerson && c.id != null && c.id !== "" ? `查看「${c.name}」的出演作品` : undefined}
                    style={{ display: "flex", gap: 8, padding: 8, border: "1px solid var(--panel-border)", borderRadius: "var(--radius-card)", background: "var(--panel)", minWidth: 0, cursor: onOpenPerson && c.id != null && c.id !== "" ? "pointer" : "default" }}>
                    {c.image_url ? (
                      <img src={c.image_url} alt="" loading="lazy" onError={(e) => { e.target.style.visibility = "hidden"; }}
                        style={{ width: 40, height: 54, borderRadius: "var(--radius-cover)", objectFit: "cover", flexShrink: 0 }} />
                    ) : (
                      <div style={{ width: 40, height: 54, borderRadius: "var(--radius-cover)", background: "var(--card-thumb)", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-secondary)", fontSize: 16 }}>{(c.name || "?").slice(0, 1)}</div>
                    )}
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</div>
                      {c.relation ? <div style={{ fontSize: 10, color: "var(--text-secondary)" }}>{c.relation}</div> : null}
                      {(c.actors || []).length > 0 ? <div style={{ fontSize: 10, color: "var(--text-secondary)", marginTop: 2 }}>CV：{(c.actors || []).join(" / ")}</div> : null}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* Phase 3-1：这个世界结束处的外部操作（收藏入库/安利卡/刷新），由调用方传回调 */}
        {(onSaveDetail || onShareDetail || onRefreshDetail) && (
          <div className="wd-actions">
            {onSaveDetail && (
              <button onClick={onSaveDetail}
                className="px-3 py-1.5 text-[12px] font-medium"
                style={{ backgroundColor: "var(--accent)", color: "#fff", borderRadius: "var(--radius-control)" }}>收藏入库</button>
            )}
            {onShareDetail && (
              <button onClick={onShareDetail}
                className="px-3 py-1.5 text-[12px] font-medium"
                style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)", borderRadius: "var(--radius-control)" }}>生成安利卡</button>
            )}
            {onRefreshDetail && (
              <button onClick={onRefreshDetail}
                className="px-3 py-1.5 text-[12px]"
                style={{ backgroundColor: "var(--tag-bg)", color: "var(--tag-text)", borderRadius: "var(--radius-control)" }}
                title="重新从数据源下载最新简介与角色小传（受限流约束）">刷新资料</button>
            )}
          </div>
        )}

        {/* 我与它（Phase 3-2-B）：我与这部作品的关系——当前状态/态度/评价/书评/带回书架。
            数据优先、关系其次、操作最后；不构成后台表单。 */}
        {detail && (
        <>
        <section className="mt-8 pt-6 border-t" style={{ borderColor: "var(--panel-border)" }}>
          <div className="flex items-baseline gap-3">
            <h3 className="wd-chapter-title">我与它</h3>
            <span className="wd-meta" style={{ fontSize: 10, letterSpacing: "0.2em" }}>MY RELATION</span>
          </div>
          <div className="wd-chapter-rule" />
          {detail.source !== "local" ? (
            <div className="wd-relation">
              <div className="wd-relation-row">
                <span className="wd-catalog-label">当前状态</span>
                <div className="wd-relation-value">
                  <span className="wd-status">{colStatus || "未收藏"}</span>
                  <select value={colStatus} onChange={(e) => { setColStatus(e.target.value); patchCollection({ status: e.target.value }); }}
                    disabled={colSaving} title="收藏状态（可手动修正）"
                    className="px-2 py-1 text-[11px] outline-none"
                    style={{ backgroundColor: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)", borderRadius: "var(--radius-control)" }}>
                    <option value="">未收藏</option>
                    {COLLECTION_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
              </div>
              {/* Phase 10-1-C-2：看完 = 记录此刻的自然时机——就近 quiet 提示（非 CTA，仅状态=看完） */}
              {colStatus === "看完" && (
                <p className="wd-hint" style={{ marginTop: "var(--sp-2)" }}>
                  刚看完的话，写一句此刻的感想——它会进入时间轴，成为 Ask 回想这一刻的线索。
                </p>
              )}
              <div className="wd-relation-row">
                <span className="wd-catalog-label">我的态度</span>
                <div className="wd-relation-value">
                  <button onClick={() => patchCollection({ favorite: !favorite })} disabled={colSaving}
                    title="是否喜欢"
                    className="px-2.5 py-1 text-[11px]"
                    style={{ color: favorite ? "var(--accent)" : "var(--text-secondary)",
                      backgroundColor: favorite ? "var(--accent-soft)" : "transparent",
                      borderRadius: "var(--radius-control)" }}>
                    {favorite ? "♡ 喜欢" : "♡ 标记喜欢"}
                  </button>
                </div>
              </div>
              {detail.my_rating != null && (
                <div className="wd-relation-row">
                  <span className="wd-catalog-label">我的评价</span>
                  <div className="wd-relation-value">
                    <span className="wd-status">我的平均 ★{detail.my_rating}</span>
                    <span className="wd-hint">（来自书评）</span>
                  </div>
                </div>
              )}
              <div className="wd-relation-row">
                <span className="wd-catalog-label">我的书评</span>
                <div className="wd-relation-value">
                  <button onClick={() => onOpenReview && onOpenReview({ id: detail.id, title: detail.title })}
                    title="打开书评工作室"
                    className="px-2.5 py-1 text-[11px]"
                    style={{ color: "var(--accent)", backgroundColor: "var(--accent-soft)", borderRadius: "var(--radius-control)" }}>
                    书评
                  </button>
                </div>
              </div>
              {detail.collected_at && (
                <div className="wd-relation-row">
                  <span className="wd-catalog-label">带回书架</span>
                  <div className="wd-relation-value">
                    <span className="wd-status">收藏于 {String(detail.collected_at).slice(0, 10)}</span>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="wd-hint">本地笔记没有收藏关系。</div>
          )}
        </section>

        {/* 相遇纪事（Phase 3-2-C-1 / ADR 0076）：开放式档案时间记录，非 Card 列表。
            事件仅来自 buildEncounterEvents；无事件整章隐藏；不显示「第一次遇见」。 */}
        {encounterEvents.length > 0 && (
          <section className="mt-8 pt-6 border-t" style={{ borderColor: "var(--panel-border)" }}>
            <div className="flex items-baseline gap-3">
              <h3 className="wd-chapter-title">相遇纪事</h3>
              <span className="wd-meta" style={{ fontSize: 10, letterSpacing: "0.2em" }}>ENCOUNTER CHRONICLE</span>
            </div>
            <div className="wd-chapter-rule" />
            <div className="wd-encounter">
              {encounterEvents.map((ev) => (
                <div key={ev.id} className="wd-encounter-item">
                  <div className="wd-encounter-date">{encounterDate(ev.occurredAt)}</div>
                  <div className="wd-encounter-body">
                    <div className="wd-encounter-title">{ev.title}</div>
                    {ev.metadata && (ev.metadata.rating != null || ev.metadata.status || ev.metadata.emotion) && (
                      <div className="wd-encounter-meta">
                        {ev.metadata.rating != null && <span>我的评分 {ev.metadata.rating}</span>}
                        {ev.metadata.status && <span>{ev.metadata.rating != null ? " · " : ""}状态 · {ev.metadata.status}</span>}
                        {ev.metadata.emotion && <span>{ev.metadata.rating != null || ev.metadata.status ? " · " : ""}情绪 · {ev.metadata.emotion}</span>}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* 我的记忆（Phase 3-2-D）：我主动留下的 Memory——composer + MemoryTimeline */}
        <section className="mt-8 pt-6 border-t" style={{ borderColor: "var(--panel-border)" }}>
          <div className="flex items-baseline gap-3">
            <h3 className="wd-chapter-title">我的记忆</h3>
            <span className="wd-meta" style={{ fontSize: 10, letterSpacing: "0.2em" }}>MY MEMORY</span>
          </div>
          <div className="wd-chapter-rule" />
          {detail.source !== "local" && (
            <div className="mc mb-5">
              {/* Phase 10-1-A-1 / C-1：零记录空态引导——说明记录的去处与 Ask 回想价值 */}
              {memReady && memories.length === 0 && reviews.length === 0 && (
                <p className="mc-empty-hint">
                  这部作品还没有你的记录——写一句此刻的感想即可，之后它会出现在时间轴与往年今日里，
                  也会成为 Ask 回想你与它经历的线索。
                </p>
              )}
              {/* 主书写区：textarea 为第一视觉焦点（Phase 4-1「留下这一刻」） */}
              <textarea ref={(el) => {
                composerRef.current = el;
                if (el && composerFocusTick > 0) el.focus(); // 收藏引导：挂载即聚焦（含异步加载后）
              }}
                value={draft} onChange={(e) => setDraft(e.target.value)}
                placeholder="写一句此刻的感想…（轻量记录，不写正式书评）"
                rows={2} className="mc-write"
                aria-label="记下一句此刻的感想" />
              {/* 辅助操作层（Phase 4-2）：情绪 / 附图——安静、不抢焦点 */}
              <div className="mc-aux">
                <select value={draftEmotion} onChange={(e) => setDraftEmotion(e.target.value)}
                  title="情绪（可选）" aria-label="情绪"
                  className="mc-select">
                  <option value="">情绪</option>
                  {MEMORY_EMOTIONS.map((e) => <option key={e} value={e}>{e}</option>)}
                </select>
                <input type="file" accept="image/*" hidden ref={fileInputRef}
                  onChange={(e) => setDraftFile(e.target.files?.[0] || null)} />
                <button onClick={() => fileInputRef.current?.click()} title="附带一张图片"
                  aria-label="附一张图片" className="mc-attach">
                  {draftFile ? "已附图 ✓" : "附一张图"}
                </button>
              </div>
              {/* Phase 10-1-C-1：价值说明——极轻一行，解释情绪/里程碑的去处（非 CTA） */}
              <p className="mc-value-hint">
                情绪和里程碑，会帮助时间轴与 Ask 回想这是怎样的一刻。
              </p>
              {/* 主操作：唯一实心 accent（Phase 4-2 独立成行，视觉最明确） */}
              <div className="mc-actions">
                <button onClick={() => submitDirect("text", draft)} disabled={!draft.trim() || recording}
                  className="mc-submit"
                  style={{ backgroundColor: "var(--accent)", color: "#fff", borderRadius: "var(--radius-control)" }}>
                  记录这一刻
                </button>
              </div>
              {/* 提交反馈（Phase 4-3）：安静一行，aria-live polite；常驻 min-height 防布局跳动 */}
              <div className="mc-feedback" aria-live="polite">
                {feedback && (
                  <span className={feedback.kind === "error" ? "mc-feedback-err" : ""}>{feedback.text}</span>
                )}
              </div>
              {/* 完成 / 重新打开：安静文字操作（文案即 milestone summary 业务语义） */}
              <div className="mc-milestone">
                <button onClick={() => submitDirect("milestone", "完成了这部作品。")} disabled={recording}
                  className="mc-milestone-btn">✓ 完成了</button>
                <button onClick={() => submitDirect("milestone", "重新打开了这部作品。")} disabled={recording}
                  className="mc-milestone-btn">↺ 重新打开</button>
              </div>
            </div>
          )}
          <MemoryTimeline itemId={itemId} refreshKey={timelineRefresh} memories={memories} />
        </section>
        </>
        )}
      </div>
    </div>
  );
}
