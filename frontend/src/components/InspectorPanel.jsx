// Text & Vector Storage Inspector 面板
// 顶部 4 指标卡 + 左下环形图(来源分布) + 右下横向条形图(Top 10 大文件)
import React, { useEffect, useState } from "react";
import { fetchStats } from "../api.js";

const DIST_COLORS = {
  Markdown: "#c084fc",
  PDF: "#ec4899",
  "Web Crawl": "#22d3ee",
  TXT: "#fbbf24",
  其他: "#94a3b8",
};

function fmtBytes(n) {
  if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(1) + " KB";
  return n + " B";
}

function fmtInt(n) {
  if (n >= 10000) return (n / 10000).toFixed(1) + "w";
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}

// 环形图（SVG stroke-dasharray）
function Donut({ distribution }) {
  const total = distribution.reduce((s, d) => s + d.count, 0);
  const r = 54;
  const C = 2 * Math.PI * r;
  let acc = 0;
  const segments = distribution.filter((d) => d.count > 0).map((d) => {
    const frac = total ? d.count / total : 0;
    const seg = { ...d, frac, start: acc, dash: frac * C };
    acc += frac;
    return seg;
  });

  return (
    <div className="flex items-center gap-4">
      <svg width="140" height="140" viewBox="0 0 140 140" className="shrink-0">
        <circle cx="70" cy="70" r={r} fill="none"
          stroke="rgba(255,255,255,0.08)" strokeWidth="16" />
        {segments.map((s, i) => (
          <circle key={i} cx="70" cy="70" r={r} fill="none"
            stroke={DIST_COLORS[s.label] || "#94a3b8"}
            strokeWidth="16" strokeLinecap="butt"
            strokeDasharray={`${Math.max(s.dash - 2, 0)} ${C}`}
            transform={`rotate(${s.start * 360 - 90} 70 70)`} />
        ))}
        <text x="70" y="66" textAnchor="middle" fontSize="20" fontWeight="700"
          fill="var(--text)">{total}</text>
        <text x="70" y="84" textAnchor="middle" fontSize="10"
          fill="var(--text-secondary)">条目</text>
      </svg>
      <div className="flex flex-col gap-1.5">
        {segments.map((s, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className="w-2.5 h-2.5 rounded-full"
              style={{ backgroundColor: DIST_COLORS[s.label] || "#94a3b8" }} />
            <span style={{ color: "var(--text)" }}>{s.label}</span>
            <span style={{ color: "var(--text-secondary)" }}>{s.count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// 横向条形图（Top 10 大文件）
function TopBars({ files }) {
  const max = files.length ? files[0].chars : 1;
  return (
    <div className="flex flex-col gap-2">
      {files.length === 0 && (
        <div className="text-xs" style={{ color: "var(--text-secondary)" }}>暂无文本条目</div>
      )}
      {files.slice(0, 10).map((f, i) => {
        const pct = Math.max((f.chars / max) * 100, 2);
        return (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className="w-24 truncate shrink-0" title={f.title}
              style={{ color: "var(--text)" }}>{f.title}</span>
            <div className="flex-1 h-3 rounded-full overflow-hidden"
              style={{ backgroundColor: "rgba(255,255,255,0.08)" }}>
              <div className="h-full rounded-full"
                style={{ width: `${pct}%`,
                  background: "linear-gradient(90deg, #c084fc, #ec4899)" }} />
            </div>
            <span className="w-12 text-right shrink-0"
              style={{ color: "var(--text-secondary)" }}>{fmtInt(f.chars)}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function InspectorPanel() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [now, setNow] = useState(() => new Date());

  const load = () => {
    setError("");
    fetchStats()
      .then((d) => { setData(d); setNow(new Date()); })
      .catch((e) => setError(e.message));
  };

  useEffect(() => {
    load();
  }, []);

  const dateStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;

  const cards = data ? [
    { label: "Total Characters", value: fmtInt(data.total_chars), badge: "字符" },
    { label: "Token Estimate", value: fmtInt(data.total_tokens), badge: "~tokens" },
    { label: "Vector DB Size", value: fmtBytes(data.vector_db_size), badge: "Chroma" },
    { label: "Chunk Count", value: fmtInt(data.chunk_count), badge: "块" },
  ] : [];

  return (
    <div className="desk-askbar rounded-2xl p-5"
      style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", backdropFilter: "blur(16px)" }}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium tracking-wide">Text &amp; Vector Storage Inspector</h3>
        <div className="flex items-center gap-2">
          <span className="text-xs px-2 py-0.5 rounded-full"
            style={{ backgroundColor: "var(--tag-bg)", color: "var(--tag-text)" }}>{dateStr}</span>
          <button onClick={load}
            className="px-2 py-0.5 rounded-lg text-xs"
            style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
            刷新
          </button>
        </div>
      </div>

      {error && <p className="text-xs mb-3" style={{ color: "var(--danger)" }}>{error}</p>}

      {/* Top Row: 4 metric cards */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        {cards.length === 0
          ? Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="rounded-xl p-3"
                style={{ backgroundColor: "rgba(255,255,255,0.06)" }}>
                <div className="h-3 w-16 rounded mb-2" style={{ backgroundColor: "rgba(255,255,255,0.1)" }} />
                <div className="h-6 w-20 rounded" style={{ backgroundColor: "rgba(255,255,255,0.08)" }} />
              </div>
            ))
          : cards.map((c, i) => (
              <div key={i} className="rounded-xl p-3"
                style={{ backgroundColor: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.08)" }}>
                <div className="text-[10px] mb-1 truncate" style={{ color: "var(--text-secondary)" }}>{c.label}</div>
                <div className="text-xl font-bold" style={{ color: "var(--accent)" }}>{c.value}</div>
                <div className="text-[10px] mt-0.5" style={{ color: "var(--text-secondary)" }}>{c.badge}</div>
              </div>
            ))}
      </div>

      {/* Bottom: donut + bars */}
      {data && (
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs mb-2" style={{ color: "var(--text-secondary)" }}>文本来源分布</div>
            <Donut distribution={data.distribution} />
          </div>
          <div>
            <div className="text-xs mb-2" style={{ color: "var(--text-secondary)" }}>Top {Math.min(data.top_files.length, 10)} 大文本文件</div>
            <TopBars files={data.top_files} />
          </div>
        </div>
      )}
    </div>
  );
}
