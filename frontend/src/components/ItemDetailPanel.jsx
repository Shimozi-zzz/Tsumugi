// 主从视图的"从"面板（ADR 0029）：点击左侧列表条目，这里**立即**更新详情。
// 复用 InfoTable（属性表格）+ TagCapsule（标签胶囊）+ 完整简介 + 角色紧凑列表，
// 独立滚动，不跳转/不弹层。
// ADR 0034：封面动态取色氛围——封面主色调作为表面色之上的柔和角部光晕（box-shadow
// 平滑过渡），不覆盖文字/按钮；浅色主题克制、深色稍明显（--ambient-alpha）。
import React, { useEffect, useState } from "react";
import { fetchItemDetail, filePathToUrl } from "../api.js";
import { InfoTable, TagCapsule, itemInfoRows } from "./ui.jsx";
import { extractPalette } from "../ambient.js";

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
            <h2 className="text-base font-semibold leading-snug" style={{ color: "var(--text)" }}>{detail.title}</h2>
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
      </div>
    </div>
  );
}
