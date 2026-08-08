// 主从视图的"从"面板（ADR 0029）：点击左侧列表条目，这里**立即**更新详情。
// 复用 InfoTable（属性表格）+ TagCapsule（标签胶囊）+ 完整简介 + 角色紧凑列表，
// 独立滚动，不跳转/不弹层。
import React, { useEffect, useState } from "react";
import { fetchItemDetail, filePathToUrl } from "../api.js";
import { InfoTable, TagCapsule, itemInfoRows } from "./ui.jsx";

function introText(detail) {
  const desc = (detail?.description || "").trim();
  if (desc) return desc;
  const ref = detail?.reference_text || "";
  const m = ref.match(/^# 作品简介\s*\n+([\s\S]*?)(?=\n# |$)/m);
  return (m?.[1] || ref).trim() || "暂无简介。";
}

export default function ItemDetailPanel({ itemId, className = "" }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

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

  return (
    <div className={className}>
      <div className="flex gap-4 mb-4">
        {cover ? (
          <img src={cover} alt="" className="w-24 h-32 object-cover rounded-xl shrink-0"
            onError={(e) => { e.target.style.display = "none"; }} />
        ) : null}
        <div className="min-w-0">
          <h2 className="text-base font-semibold leading-snug" style={{ color: "var(--text)" }}>{detail.title}</h2>
          <div className="flex items-center gap-2 mt-1.5 flex-wrap">
            <TagCapsule text={detail.source || "本地"} />
            {detail.rating != null && <span className="text-xs" style={{ color: "var(--amber, #ffc24b)" }}>大众 ★{detail.rating}</span>}
            {detail.my_rating != null && <span className="text-xs" style={{ color: "var(--text-secondary)" }}>我的平均 ★{detail.my_rating}</span>}
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
  );
}
