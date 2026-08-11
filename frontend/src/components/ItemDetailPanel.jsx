// 主从视图的"从"面板（ADR 0029）：点击左侧列表条目，这里**立即**更新详情。
// 复用 InfoTable（属性表格）+ TagCapsule（标签胶囊）+ 完整简介 + 角色紧凑列表，
// 独立滚动，不跳转/不弹层。
// ADR 0034：封面动态取色氛围——封面主色调作为表面色之上的柔和角部光晕（box-shadow
// 平滑过渡），不覆盖文字/按钮；浅色主题克制、深色稍明显（--ambient-alpha）。
// Phase B（ADR 0042）：双栏结构——"外部世界"（世界如何描述它）与"我的记录"
// （我如何理解它，含 Memory 记忆时间轴）。
// Phase 3-1（ADR 0075）：ItemDetailPanel 成为**统一 Work Detail 内容基底**。
// - Classic（主从/网格/书架/角色墙/回廊/关系厅）、Mobile Detail Scene、ShellC 共用同一内容；
// - 新增外部未收藏模式：`externalDetail`（无 itemId）只呈现作品本身 + 这个世界 + 外部操作
//   （收藏入库/安利卡/刷新），回调由调用方传入（Panel 不承担新后端业务）；
// - `refreshKey` 用于"刷新资料"后重取详情。
import React, { useEffect, useRef, useState } from "react";
import { fetchItemDetail, fetchItemReviews, fetchItemMemories, filePathToUrl, updateWorkColumns, updateCollection, createDirectMemory } from "../api.js";
import { TagCapsule, itemInfoRows, WORK_TYPES, WORK_TYPE_LABEL, COLLECTION_STATUSES, MEMORY_EMOTIONS } from "./ui.jsx";
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

  // Phase 3-2-C-1（ADR 0076）：相遇纪事数据——统一在此取 reviews/memories，
  // 同一份 memories 同时供给 MemoryTimeline（避免重复请求）。
  const [reviews, setReviews] = useState([]);
  const [memories, setMemories] = useState([]);
  useEffect(() => {
    if (itemId == null) { setReviews([]); setMemories([]); return; }
    let cancelled = false;
    fetchItemReviews(itemId).then((r) => { if (!cancelled) setReviews(Array.isArray(r) ? r : []); }).catch(() => {});
    fetchItemMemories(itemId).then((m) => { if (!cancelled) setMemories(Array.isArray(m) ? m : []); }).catch(() => {});
    return () => { cancelled = true; };
  }, [itemId, timelineRefresh]);

  async function submitDirect(sourceType, text) {
    setRecording(true);
    try {
      await createDirectMemory(itemId, {
        summary: text, source_type: sourceType,
        emotion: draftEmotion, file: sourceType === "text" ? draftFile : null,
      });
      setDraft(""); setDraftEmotion(""); setDraftFile(null);
      setTimelineRefresh((k) => k + 1);
    } catch { /* 静默失败，保留输入便于重试 */ }
    finally { setRecording(false); }
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
            <div className="wd-meta mt-1.5">
              {data.source || "本地"}
              {data.rating != null && <span> · 大众 ★{data.rating}</span>}
              {data.my_rating != null && <span> · 我的平均 ★{data.my_rating}</span>}
            </div>
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

          {tags.length > 0 && (
            <div className="wd-tags">
              {tags.map((t) => <TagCapsule key={t} text={t} />)}
            </div>
          )}

          {(data.characters || []).length > 0 && (
            <div className="wd-chars">
              <div className="wd-chars-title">角色 · {data.characters.length}</div>
              <div className="flex flex-wrap gap-1.5">
                {(data.characters || []).map((c) => (
                  <TagCapsule key={c.id ?? c.name} text={c.name} title={c.summary || c.relation || undefined} />
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
              {/* 主书写区：textarea 为第一视觉焦点（Phase 4-1「留下这一刻」） */}
              <textarea value={draft} onChange={(e) => setDraft(e.target.value)}
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
              {/* 主操作：唯一实心 accent（Phase 4-2 独立成行，视觉最明确） */}
              <div className="mc-actions">
                <button onClick={() => submitDirect("text", draft)} disabled={!draft.trim() || recording}
                  className="mc-submit"
                  style={{ backgroundColor: "var(--accent)", color: "#fff", borderRadius: "var(--radius-control)" }}>
                  记录这一刻
                </button>
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
