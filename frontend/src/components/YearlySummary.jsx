// 年度总结（ADR 0033）：GitHub 贡献图风格热力图（手写 SVG，不引图表库）
// - 一格一天，按周排列成年度网格；深浅 = accent 色系 color-mix 透明度（4 档 + 空）
// - 悬停显示当天具体数据（X 条书评 · Y 个收藏）
// - 统计摘要：全年收藏/书评总数、最活跃月份、最长连续活跃、活跃天数
import React, { useEffect, useMemo, useState } from "react";
import { fetchActivity } from "../api.js";
import { ArchiveNo } from "./ui.jsx";

const CELL = 11;        // 单元格尺寸
const GAP = 2;          // 间距
const LEVELS = [0, 1, 2, 3, 4];
const LEVEL_PCT = [0, 18, 34, 52, 70]; // accent 透明度百分比（color-mix，克制）

function levelOf(score) {
  if (score <= 0) return 0;
  if (score === 1) return 1;
  if (score <= 3) return 2;
  if (score <= 7) return 3;
  return 4;
}

function localIso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function fmtDate(s) {
  const [y, m, d] = s.split("-");
  return `${y} 年 ${Number(m)} 月 ${Number(d)} 日`;
}

// 构建年度网格：从元旦对齐到周日，直到今天（含未来格为空占位）
function buildGrid(year, today) {
  const start = new Date(year, 0, 1);
  const colStart = new Date(year, 0, 1 - start.getDay()); // 对齐到周日
  const end = today;
  const dayCount = Math.round((end - colStart) / 86400000) + 1;
  const cols = Math.ceil(dayCount / 7);
  const cells = [];
  const monthCol = {}; // 月份(1-12) -> 首列索引
  for (let c = 0; c < cols; c++) {
    for (let r = 0; r < 7; r++) {
      const d = new Date(colStart);
      d.setDate(d.getDate() + c * 7 + r);
      const iso = localIso(d);
      if (d.getDate() === 1 && d.getMonth() === 0 && c > 0 && monthCol[1] === undefined) {
        // 1 月已在首列
      }
      if (d.getDate() === 1 && monthCol[d.getMonth() + 1] === undefined) {
        monthCol[d.getMonth() + 1] = c;
      }
      const inYear = d.getFullYear() === year;
      const past = d <= today;
      cells.push({ iso, r, c, inYear, past });
    }
  }
  return { cols, cells, monthCol };
}

export default function YearlySummary({ year: propYear, className = "" }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [year, setYear] = useState(() => propYear || new Date().getFullYear());
  const [today, setToday] = useState(() => {
    const t = new Date();
    t.setHours(0, 0, 0, 0);
    return t;
  });

  useEffect(() => { setYear(propYear || new Date().getFullYear()); }, [propYear]);

  useEffect(() => {
    setLoading(true); setError("");
    fetchActivity(year)
      .then((d) => { setData(d); setToday((() => { const t = new Date(); t.setHours(0, 0, 0, 0); return t; })()); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [year]);

  const dayMap = useMemo(() => {
    const m = {};
    for (const d of data?.days || []) m[d.date] = d;
    return m;
  }, [data]);

  const grid = useMemo(() => (year ? buildGrid(year, today) : null), [year, today]);

  if (loading) return <div className={"text-sm " + className} style={{ color: "var(--text-secondary)" }}>加载中…</div>;
  if (error) return <div className={"text-sm " + className} style={{ color: "var(--danger)" }}>{error}</div>;
  if (!data || !grid) return null;

  const s = data.stats || {};
  const stats = [
    { label: "全年收藏", value: s.total_collections ?? 0, sub: "外部收藏入库" },
    { label: "书评总数", value: s.total_reviews ?? 0, sub: "写的读后感" },
    { label: "活跃天数", value: s.active_days ?? 0, sub: "有记录的天数" },
    { label: "最长连续活跃", value: s.longest_streak ?? 0, sub: "天" },
  ];
  const sw = CELL + GAP;
  const height = 7 * sw;

  return (
    <div className={className}>
      {/* 年度档案头（Phase 6-1）：ArchiveNo 年份 + mono + hairline；传说克制 */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-baseline gap-3">
          <ArchiveNo size="lg">{year}</ArchiveNo>
          <span className="wd-meta" style={{ fontSize: 10, letterSpacing: "0.2em" }}>ANNUAL ARCHIVE</span>
        </div>
        <div className="flex items-center gap-1 text-[10px]" style={{ color: "var(--ink-2)" }}>
          <span>少</span>
          {LEVELS.map((l) => (
            <span key={l} className="ys-legend-cell"
              style={{ backgroundColor: l === 0 ? "var(--surface-2)" : `color-mix(in srgb, var(--accent) ${LEVEL_PCT[l]}%, transparent)` }} />
          ))}
          <span className="ml-1">多</span>
        </div>
      </div>
      <div className="wd-chapter-rule" />
      <p className="ys-weight-note">
        活跃度 = 书评×{data.weights?.review ?? 2} + 收藏×{data.weights?.collection ?? 1}
      </p>

      {/* 年度活动时间记录（Phase 6-1：纸面 hairline 容器，去 Dashboard 卡片） */}
      <div className="border p-3 overflow-x-auto mt-3"
        style={{ backgroundColor: "var(--surface-1)", borderColor: "var(--panel-border)", borderRadius: "var(--radius-card)" }}>
        <svg width={grid.cols * sw} height={height + 18} viewBox={`0 0 ${grid.cols * sw} ${height + 18}`} role="img" aria-label={`${year} 年活跃度热力图`}>
          {Object.entries(grid.monthCol).map(([m, col]) => (
            <text key={m} x={col * sw + CELL / 2} y={10} fontSize="9" textAnchor="middle"
              fill="var(--text-secondary)">{m}</text>
          ))}
          {/* 星期标签（Mon/Wed/Fri） */}
          {[[1, "一"], [3, "三"], [5, "五"]].map(([r, label]) => (
            <text key={r} x={-2} y={18 + r * sw + CELL / 2 + 3} fontSize="8" textAnchor="end"
              fill="var(--text-secondary)">{label}</text>
          ))}
          {grid.cells.map((cell) => {
            const day = dayMap[cell.iso];
            const score = day ? day.score : 0;
            const level = cell.past && cell.inYear ? levelOf(score) : 0;
            const fill = level === 0
              ? (cell.past && cell.inYear ? "var(--surface-2)" : "transparent")
              : `color-mix(in srgb, var(--accent) ${LEVEL_PCT[level]}%, transparent)`;
            const tip = day
              ? `${fmtDate(cell.iso)}：${day.reviews} 条书评 · ${day.collections} 个收藏`
              : fmtDate(cell.iso);
            return (
              <rect key={cell.iso} x={cell.c * sw} y={18 + cell.r * sw} width={CELL} height={CELL}
                rx={2.5} fill={fill}>
                <title>{tip}</title>
              </rect>
            );
          })}
        </svg>
      </div>

      {/* 年度统计（Phase 6-1：quiet catalog 行，去数字卡片墙） */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 mt-5">
        {stats.map((c) => (
          <div key={c.label} className="ys-stat-row">
            <span className="ys-stat-label">{c.label}</span>
            <span className="ys-stat-value">{c.value}</span>
            <span className="ys-stat-sub">{c.sub}</span>
          </div>
        ))}
      </div>
      {s.busiest_month && (
        <p className="text-xs mt-3" style={{ color: "var(--text-secondary)" }}>
          最活跃月份：<b style={{ color: "var(--text)" }}>{s.busiest_month}</b>
          （按活跃度得分）
        </p>
      )}
    </div>
  );
}
