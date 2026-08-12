// 记忆回廊（Phase C / ADR 0043）：全局记忆浏览，仅自由查询
// - 数据：调 Phase A 的 GET /memories 拉全量（个人库体量小，一次拉全量后客户端
//   按年份/作品筛选；后端接口已支持 server 侧筛选，数据量大后再迁移分页，见 ADR）；
// - 展示形式：**按年份分组的编年列表**（"回廊"隐喻：一层一层往回走，年标签如书档），
//   条目 = 日期 + 作品名 + 摘要；点击条目跳转到对应作品的主从详情；
// - 筛选：年份（来自数据的年份 chip）+ 作品（下拉）；
// - 本轮明确不做：意外重逢（Phase E）、轻量记录（Phase D）、标签/语义筛选（结构化筛选）。
import React, { useEffect, useMemo, useState } from "react";
import { fetchMemories } from "../api.js";
import { ArchiveNo, MemoryTypeTag } from "./ui.jsx";

function yearOf(iso) {
  return iso ? String(iso).slice(0, 4) : "";
}
function md(iso) {
  const s = String(iso || "");
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[2]}-${m[3]}` : s.slice(5, 10);
}

export default function MemoryGallery({ onOpenWork, className = "", showHeader = true }) {
  const [memories, setMemories] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [year, setYear] = useState(null);   // null = 全部年份
  const [itemId, setItemId] = useState(null); // null = 全部作品
  const [q, setQ] = useState("");            // 文本筛（summary 子串，与后端 ?search= 字段一致）

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    fetchMemories({ limit: 500 })
      .then((m) => { if (!cancelled) setMemories(m || []); })
      .catch((e) => { if (!cancelled) { setError(e.message); setMemories([]); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // 全部记忆按时间倒序（最新在前，回廊从"现在"往"过去"走）
  const sorted = useMemo(() => [...memories].sort((a, b) => {
    const ta = new Date(a.occurred_at).getTime() || 0;
    const tb = new Date(b.occurred_at).getTime() || 0;
    return ta === tb ? (b.id - a.id) : (tb - ta);
  }), [memories]);

  const years = useMemo(() => [...new Set(sorted.map((m) => yearOf(m.occurred_at)).filter(Boolean))].sort().reverse(), [sorted]);
  const works = useMemo(() => {
    const map = new Map();
    for (const m of sorted) {
      if (m.item_id != null && !map.has(m.item_id)) map.set(m.item_id, m.item_title || `作品 #${m.item_id}`);
    }
    return [...map.entries()].sort((a, b) => (a[1] || "").localeCompare(b[1] || "", "zh"));
  }, [sorted]);

  const filtered = useMemo(() => sorted.filter((m) => {
    if (year && yearOf(m.occurred_at) !== year) return false;
    if (itemId != null && m.item_id !== itemId) return false;
    // Phase D（ADR 0063）：文本筛复用后端 /memories?search= 的字段（summary 子串，大小写不敏感）
    const kw = q.trim().toLowerCase();
    if (kw && !(m.summary || "").toLowerCase().includes(kw)) return false;
    return true;
  }), [sorted, year, itemId, q]);

  // 按年份分组（年过滤激活时不再重复展示年头）
  const groups = useMemo(() => {
    if (year) return [{ year, items: filtered }];
    const g = [];
    for (const y of years) {
      const items = filtered.filter((m) => yearOf(m.occurred_at) === y);
      if (items.length) g.push({ year: y, items });
    }
    return g;
  }, [filtered, years, year]);

  let body;
  if (loading) {
    body = <div className="text-xs" style={{ color: "var(--text-secondary)" }}>正在翻阅馆藏…</div>;
  } else if (error) {
    body = <div className="text-xs" style={{ color: "var(--danger)" }}>{error}</div>;
  } else if (memories.length === 0) {
    body = (
      <div className="text-[13px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
        记忆回廊还是空的。收藏作品、写书评、留下记录，这里会慢慢长出属于你和这些作品的记忆。
      </div>
    );
  } else if (filtered.length === 0) {
    const kw = q.trim();
    body = (
      <div className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
        {kw
          ? `没有找到包含「${kw}」的记忆。`
          : (year ? `还没有 ${year} 年的记忆。` : "这个作品还没有留下记忆。")}
      </div>
    );
  } else {
    body = (
      <div className="space-y-6">
        {groups.map((g) => (
          <section key={g.year}>
            <div className="flex items-baseline gap-2 mb-2">
              <ArchiveNo size="lg">{g.year}</ArchiveNo>
              <span className="h-px flex-1 self-center" style={{ backgroundColor: "var(--panel-border)" }} />
              <span className="text-[10px] tabular-nums tracking-wider"
                style={{ color: "var(--ink-2)", fontFamily: "var(--font-mono)" }}>{g.items.length} 条</span>
            </div>
            {/* 记忆标本行（Phase 5-2-1）：去竖线 rail / accent 圆点，克制档案行——
                日期(mono) + 类型 + 作品 · 摘要 · 情绪(存在时) · 附图缩略图(存在时) */}
            <div className="flex flex-col gap-1">
              {g.items.map((m) => (
                <button key={m.id} type="button" onClick={() => onOpenWork?.(m.item_id)}
                  title="打开这部作品" className="mg-specimen">
                  <span className="mg-specimen-meta">
                    <span className="mg-specimen-date">{md(m.occurred_at)}</span>
                    {m.source_type !== "review" && <MemoryTypeTag sourceType={m.source_type} />}
                    <span className="mg-specimen-work"> · {m.item_title || `作品 #${m.item_id}`}</span>
                  </span>
                  <span className="mg-specimen-summary">{m.summary || "（无摘要）"}</span>
                  {m.emotion && <span className="mg-specimen-emotion">情绪 · {m.emotion}</span>}
                  {(m.media || []).length > 0 && (
                    <span className="mg-specimen-media">
                      {m.media.slice(0, 2).map((med) => (
                        <img key={med.id} src={med.url} alt=""
                          className="mg-specimen-thumb" />
                      ))}
                    </span>
                  )}
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>
    );
  }

  return (
    <div className={className}>
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div>
          {showHeader && (
            <>
              <h2 className="tsm-heading leading-snug" style={{ color: "var(--text)", fontSize: 20, fontWeight: 600 }}>记忆回廊</h2>
              <div className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
                这座图书馆记得你做过什么（按年份 / 作品 / 文本筛选）
              </div>
            </>
          )}
        </div>
        {/* 文本筛 + 作品筛选（Phase 5-1：radius 收敛到 --radius-control，保持原生语义） */}
        <div className="flex items-center gap-2 flex-wrap">
          <input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="搜索记忆内容…"
            aria-label="搜索记忆"
            className="px-3 py-1.5 text-xs outline-none w-44"
            style={{ backgroundColor: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)", borderRadius: "var(--radius-control)" }} />
          {q && (
            <button onClick={() => setQ("")} title="清除搜索"
              className="text-[11px] px-1" style={{ color: "var(--text-secondary)" }}>✕</button>
          )}
          {works.length > 0 && (
            <select value={itemId ?? ""} onChange={(e) => setItemId(e.target.value ? Number(e.target.value) : null)}
              className="px-3 py-1.5 text-xs outline-none max-w-[240px]"
              style={{ backgroundColor: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)", borderRadius: "var(--radius-control)" }}>
              <option value="">全部作品</option>
              {works.map(([id, title]) => <option key={id} value={id}>{title}</option>)}
            </select>
          )}
        </div>
      </div>

      {/* 年份筛选（Phase 5-1：去白字实心 accent，克制 chip——active=accent-soft+accent） */}
      {years.length > 0 && (
        <div className="flex items-center gap-1.5 mb-4 flex-wrap">
          <button onClick={() => setYear(null)}
            className="px-2.5 py-1 rounded-full text-xs transition-colors"
            style={{ color: year === null ? "var(--accent)" : "var(--text-secondary)",
              backgroundColor: year === null ? "var(--accent-soft)" : "transparent" }}>
            全部
          </button>
          {years.map((y) => (
            <button key={y} onClick={() => setYear(year === y ? null : y)}
              className="px-2.5 py-1 rounded-full text-xs transition-colors"
              style={{ color: year === y ? "var(--accent)" : "var(--text-secondary)",
                backgroundColor: year === y ? "var(--accent-soft)" : "transparent" }}>
              {y}
            </button>
          ))}
        </div>
      )}

      {body}
    </div>
  );
}
