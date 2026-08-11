// 图书馆网格视图 · 三个探索性视觉方向（ADR 0055，非正式主题）
// A 深夜书房：近黑背景 + 封面取色氛围光为主视觉（像深夜被台灯照亮的书）
// B 编目抽屉：纸感档案卡 / 索书卡版式（等宽+衬线强对比、粗重编号、密集信息）
// C 展览橱窗：美术馆橱窗（大留白、不规则展示单元、少而精、非对称）
// 本轮允许偏离 ADR 0020 token；选中哪个方向后再做 token 融入。真实数据渲染。
import React, { useEffect, useState } from "react";
import { extractPalette } from "../ambient.js";

export const GRID_CONCEPTS = [
  { key: "classic", label: "经典档案卡" },
  { key: "a", label: "A 深夜书房" },
  { key: "b", label: "B 编目抽屉" },
  { key: "c", label: "C 展览橱窗" },
];

export function parseConcept(raw) {
  return GRID_CONCEPTS.some((c) => c.key === raw) ? raw : null;
}

function usePalette(cover) {
  const [pal, setPal] = useState(null);
  useEffect(() => {
    let cancelled = false;
    if (!cover) { setPal(null); return; }
    extractPalette(cover).then((p) => { if (!cancelled) setPal(p && p.primary ? p.primary : null); }).catch(() => {});
    return () => { cancelled = true; };
  }, [cover]);
  return pal;
}

function no(it) {
  return String(it.id != null ? it.id : 0).padStart(4, "0");
}

/* ================= 方向 A：深夜书房 ================= */
export function GridConceptA({ items, coverOf, onOpenItem }) {
  return (
    <div className="concept-a" data-concept="a">
      <p className="concept-a-intro">夜里关灯之后，只有手边的书是亮的。</p>
      <div className="concept-a-cards">
        {items.map((it) => <BookA key={it.id} it={it} cover={coverOf(it)} onOpen={() => onOpenItem(it)} />)}
      </div>
    </div>
  );
}
function BookA({ it, cover, onOpen }) {
  const primary = usePalette(cover);
  const rgb = primary ? `${primary.r},${primary.g},${primary.b}` : null;
  return (
    <button className="concept-a-card" onClick={onOpen} title={it.title}>
      {rgb && (
        <span className="concept-a-glow"
          style={{ background: `radial-gradient(80% 70% at 50% 45%, rgba(${rgb},0.60), rgba(${rgb},0.18) 55%, transparent 75%)` }} />
      )}
      <span className="concept-a-cover">
        {cover ? <img src={cover} alt={it.title} loading="lazy" /> : <span className="concept-a-fallback">{no(it)}</span>}
      </span>
      <span className="concept-a-title">{it.title}</span>
      <span className="concept-a-no">NO.{no(it)}</span>
    </button>
  );
}

/* ================= 方向 B：编目卡片抽屉 ================= */
export function GridConceptB({ items, coverOf, onOpenItem }) {
  return (
    <div className="concept-b" data-concept="b">
      <p className="concept-b-intro">检索台 · 索书卡</p>
      <div className="concept-b-cards">
        {items.map((it) => (
          <button key={it.id} className="concept-b-card" onClick={() => onOpenItem(it)} title={it.title}>
            <div className="concept-b-top">
              <span className="concept-b-no">NO.{no(it)}</span>
              <span className="concept-b-source">{it.source === "local" ? "笔记" : it.source}</span>
            </div>
            <h3 className="concept-b-title">{it.title}</h3>
            <div className="concept-b-cover">
              {coverOf(it) ? <img src={coverOf(it)} alt={it.title} loading="lazy" /> : <span className="concept-b-fallback">藏 · {no(it)}</span>}
            </div>
            <div className="concept-b-lines">
              <span>─ 编目号 {no(it)}</span>
              <span>─ 来源 {it.source === "local" ? "本地笔记" : it.source}</span>
              {it.chunks_count != null && <span>─ 记录 {it.chunks_count} 条</span>}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ================= 方向 C：展览橱窗 ================= */
export function GridConceptC({ items, coverOf, onOpenItem }) {
  return (
    <div className="concept-c" data-concept="c">
      <p className="concept-c-intro">每一件藏品，都值得单独被看。</p>
      <div className="concept-c-cards">
        {items.map((it, i) => {
          const wide = i % 5 === 1 || i % 5 === 4; // 不规则展示单元
          return (
            <button key={it.id} className={"concept-c-card" + (wide ? " concept-c-wide" : "")}
              onClick={() => onOpenItem(it)} title={it.title}>
              <span className="concept-c-cover">
                {coverOf(it) ? <img src={coverOf(it)} alt={it.title} loading="lazy" /> : <span className="concept-c-fallback">{no(it)}</span>}
                <span className="concept-c-no">№ {no(it)}</span>
              </span>
              <span className="concept-c-title">{it.title}</span>
              <span className="concept-c-meta">{it.source === "local" ? "本地笔记" : it.source}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ================= 方向开关 ================= */
export function GridConceptSwitcher({ value, onChange }) {
  return (
    <div className="grid-concept-switch" data-testid="grid-concept-switch">
      {GRID_CONCEPTS.map((c) => (
        <button key={c.key} onClick={() => onChange(c.key)}
          data-concept-key={c.key}
          style={{
            color: value === c.key ? "#fff" : "var(--text-secondary)",
            backgroundColor: value === c.key ? "var(--accent)" : "var(--accent-soft)",
          }}>{c.label}</button>
      ))}
    </div>
  );
}
