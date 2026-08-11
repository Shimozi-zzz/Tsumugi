// 主从视图的"从"面板（ADR 0029）：点击左侧列表条目，这里**立即**更新详情。
// 复用 InfoTable（属性表格）+ TagCapsule（标签胶囊）+ 完整简介 + 角色紧凑列表，
// 独立滚动，不跳转/不弹层。
// ADR 0034：封面动态取色氛围——封面主色调作为表面色之上的柔和角部光晕（box-shadow
// 平滑过渡），不覆盖文字/按钮；浅色主题克制、深色稍明显（--ambient-alpha）。
// Phase B（ADR 0042）：双栏结构——"外部世界"（世界如何描述它）与"我的记录"
// （我如何理解它，含 Memory 记忆时间轴）。
import React, { useEffect, useRef, useState } from "react";
import { fetchItemDetail, filePathToUrl, updateWorkColumns, updateCollection, createDirectMemory } from "../api.js";
import { InfoTable, TagCapsule, itemInfoRows, WORK_TYPES, WORK_TYPE_LABEL, COLLECTION_STATUSES, MEMORY_EMOTIONS } from "./ui.jsx";
import { extractPalette } from "../ambient.js";
import MemoryTimeline from "./MemoryTimeline.jsx";

function introText(detail) {
  const desc = (detail?.description || "").trim();
  if (desc) return desc;
  const ref = detail?.reference_text || "";
  const m = ref.match(/^# 作品简介\s*\n+([\s\S]*?)(?=\n# |$)/m);
  return (m?.[1] || ref).trim() || "暂无简介。";
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

export default function ItemDetailPanel({ itemId, className = "" }) {
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
  }, [itemId]);

  // ADR 0034：详情变化时从封面提取主色调（缓存于 ambient 模块；本地缓存封面优先，
  // 同源无 taint）。加载中保持旧氛围，新色就绪后经 box-shadow transition 平滑过渡。
  useEffect(() => {
    if (!detail) return;
    let cancelled = false;
    const coverSrc = filePathToUrl(detail?.file_path) || detail?.image_url || "";
    if (!coverSrc) { setPalette(null); return; }
    extractPalette(coverSrc).then((p) => { if (!cancelled) setPalette(p); });
    return () => { cancelled = true; };
  }, [detail]);

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

  const cover = detail.image_url || filePathToUrl(detail?.file_path) || "";
  const rows = itemInfoRows(detail);
  const tags = detail.tags || [];

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
        <div className="flex gap-4 mb-4">
          {cover ? (
            <img src={cover} alt="" className="w-24 h-32 object-cover rounded-xl shrink-0"
              onError={(e) => { e.target.style.display = "none"; }} />
          ) : null}
          <div className="min-w-0">
            <h2 className="tsm-heading leading-tight" style={{ color: "var(--text)", fontSize: 22, fontWeight: 600 }}>{detail.title}</h2>
            {detail.id != null && (
              <div className="catalog-no mt-1">NO. {String(detail.id).padStart(4, "0")}</div>
            )}
            <div className="flex items-center gap-2 mt-2 flex-wrap">
              <TagCapsule text={detail.source || "本地"} />
              {detail.rating != null && (
                <TagCapsule text={`大众 ★${detail.rating}`} title="外部数据源公众评分" />
              )}
              {detail.my_rating != null && (
                <TagCapsule text={`我的平均 ★${detail.my_rating}`} muted />
              )}
            </div>
          </div>
        </div>

        {/* 外部世界：世界如何描述它（Phase B，ADR 0042 双栏结构）
            P1（ADR 0045）：右侧提供作品类型内联修正（外部作品） */}
        <div className="mb-3 flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-baseline gap-2">
            <span className="text-[11px] tracking-wider" style={{ color: "var(--accent)" }}>外部世界</span>
            <span className="text-[11px]" style={{ color: "var(--text-secondary)" }}>· 世界如何描述它</span>
          </div>
          {detail.source !== "local" && (
            <select value={workType} onChange={changeWorkType} title="作品类型（可手动修正）"
              disabled={workSaving}
              className="rounded-lg px-2 py-1 text-[11px] outline-none"
              style={{ backgroundColor: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)" }}>
              <option value="">未分类</option>
              {WORK_TYPES.map((t) => <option key={t} value={t}>{WORK_TYPE_LABEL[t]}</option>)}
            </select>
          )}
        </div>

        {rows.length > 0 && (
          <div className="mb-4">
            <div className="text-[11px] mb-1.5 tracking-wider" style={{ color: "var(--text-secondary)" }}>基本信息</div>
            <InfoTable rows={rows} />
          </div>
        )}

        <div className="mb-4">
          <div className="text-[11px] mb-1.5 tracking-wider" style={{ color: "var(--text-secondary)" }}>简介</div>
          <div className="text-[13px] leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text)" }}>
            {introText(detail)}
          </div>
        </div>

        {tags.length > 0 && (
          <div className="mb-4 flex flex-wrap gap-1.5">
            {tags.map((t) => <TagCapsule key={t} text={t} />)}
          </div>
        )}

        {(detail.characters || []).length > 0 && (
          <div>
            <div className="text-[11px] mb-1.5 tracking-wider" style={{ color: "var(--text-secondary)" }}>
              角色（{detail.characters.length}）
            </div>
            <div className="flex flex-wrap gap-1.5">
              {(detail.characters || []).map((c) => (
                <TagCapsule key={c.id ?? c.name} text={c.name} title={c.summary || c.relation || undefined} />
              ))}
            </div>
          </div>
        )}

        {/* 我的记录：我如何理解它（Phase B，ADR 0042）——Memory 记忆时间轴
            P2（ADR 0046）：收藏状态/是否喜欢/收藏时间 内联编辑 */}
        <div className="mt-7 pt-5 border-t" style={{ borderColor: "var(--panel-border)" }}>
          <div className="mb-3 flex items-baseline gap-2">
            <span className="text-[11px] tracking-wider" style={{ color: "var(--accent)" }}>我的记录</span>
            <span className="text-[11px]" style={{ color: "var(--text-secondary)" }}>· 我如何理解它</span>
          </div>
          {detail.source !== "local" && (
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              <select value={colStatus} onChange={(e) => { setColStatus(e.target.value); patchCollection({ status: e.target.value }); }}
                disabled={colSaving} title="收藏状态（可手动修正）"
                className="rounded-lg px-2 py-1 text-[11px] outline-none"
                style={{ backgroundColor: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)" }}>
                <option value="">未标记</option>
                {COLLECTION_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <button onClick={() => patchCollection({ favorite: !favorite })} disabled={colSaving}
                title="是否喜欢"
                className="px-2.5 py-1 rounded-full text-[11px] transition-colors"
                style={{ backgroundColor: favorite ? "var(--accent)" : "var(--accent-soft)",
                  color: favorite ? "#fff" : "var(--accent)" }}>
                {favorite ? "♡ 喜欢" : "♡ 标记喜欢"}
              </button>
              {detail.collected_at && (
                <span className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                  收藏于 {String(detail.collected_at).slice(0, 10)}
                </span>
              )}
            </div>
          )}
          {/* P3（ADR 0047）：轻量记录 composer + 里程碑 */}
          {detail.source !== "local" && (
            <div className="mb-3">
              <div className="flex items-center gap-2 flex-wrap">
                <input value={draft} onChange={(e) => setDraft(e.target.value)}
                  placeholder="写一句此刻的感想…（轻量记录，不写正式书评）"
                  className="flex-1 min-w-0 rounded-lg px-3 py-1.5 text-[12px] outline-none"
                  style={{ backgroundColor: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)" }} />
                <select value={draftEmotion} onChange={(e) => setDraftEmotion(e.target.value)}
                  title="情绪（可选）"
                  className="rounded-lg px-2 py-1.5 text-[11px] outline-none"
                  style={{ backgroundColor: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)" }}>
                  <option value="">情绪</option>
                  {MEMORY_EMOTIONS.map((e) => <option key={e} value={e}>{e}</option>)}
                </select>
                <input type="file" accept="image/*" hidden ref={fileInputRef}
                  onChange={(e) => setDraftFile(e.target.files?.[0] || null)} />
                <button onClick={() => fileInputRef.current?.click()} title="附带一张图片"
                  className="px-2 py-1.5 rounded-lg text-[11px]"
                  style={{ color: "var(--text-secondary)", backgroundColor: "var(--accent-soft)" }}>
                  {draftFile ? "🖼 ✓" : "🖼"}
                </button>
                <button onClick={() => submitDirect("text", draft)} disabled={!draft.trim() || recording}
                  className="px-3 py-1.5 rounded-lg text-[11px] font-medium disabled:opacity-40"
                  style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
                  记录
                </button>
              </div>
              <div className="flex items-center gap-2 mt-2">
                <button onClick={() => submitDirect("milestone", "完成了这部作品。")} disabled={recording}
                  className="px-2.5 py-1 rounded-full text-[11px]"
                  style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>✓ 完成了</button>
                <button onClick={() => submitDirect("milestone", "重新打开了这部作品。")} disabled={recording}
                  className="px-2.5 py-1 rounded-full text-[11px]"
                  style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>↺ 重新打开</button>
              </div>
            </div>
          )}
          <MemoryTimeline itemId={itemId} refreshKey={timelineRefresh} />
        </div>
      </div>
    </div>
  );
}
