// 应用外壳 · 三个空间结构探索方向（ADR 0057，沿用编目抽屉配色/字体/编号，探索空间结构）
// A 卡片抽屉导航：侧栏=真实卡片目录柜（一排带标签的抽屉，抽屉拉开式展开）
// B 书脊索引栏：左导航=一排立着的书脊，文字竖排，整条是馆藏索引书脊
// C 非对称档案室：不同页面房间格局不同（宽度/偏移/错落非对称）
// 真实数据渲染：书库(ArchiveCard)/检索台(searchMy)/回廊/人物馆/关系厅复用现有组件。
import React, { useEffect, useState } from "react";
import { fetchItems, searchMy, filePathToUrl } from "../api.js";
import ArchiveCard from "./ArchiveCard.jsx";
import MemoryGallery from "./MemoryGallery.jsx";
import CharacterWall from "./CharacterWall.jsx";
import VoiceGraphView from "./VoiceGraphView.jsx";

export const SHELL_CONCEPTS = [
  { key: "classic", label: "经典三栏" },
  { key: "a", label: "A 卡片抽屉" },
  { key: "b", label: "B 书脊索引" },
  { key: "c", label: "C 非对称档案室" },
];
export function parseShell(raw) {
  return SHELL_CONCEPTS.some((c) => c.key === raw) ? raw : null;
}

const SECTIONS = [
  { key: "library", label: "书库" },
  { key: "ask", label: "检索台" },
  { key: "gallery", label: "记忆回廊" },
  { key: "characters", label: "人物馆" },
  { key: "voice", label: "关系厅" },
  { key: "settings", label: "管理室" },
];

function coverOf(it) {
  if (it.file_path) { const u = filePathToUrl(it.file_path); if (u) return u; }
  return it.image_url || null;
}

/* ---------- 真实内容渲染器（三外壳共用） ---------- */
function ShellContent({ section }) {
  const [items, setItems] = useState([]);
  const [q, setQ] = useState("");
  const [my, setMy] = useState(null);

  useEffect(() => {
    if (section !== "library") return;
    let c = false;
    fetchItems({ limit: 48 }).then((d) => { if (!c) setItems(d.items || []); }).catch(() => {});
    return () => { c = true; };
  }, [section]);

  if (section === "library") {
    return (
      <div className="shell-grid">
        {items.map((it) => (
          <ArchiveCard key={it.id} it={it} cover={coverOf(it)} onOpen={() => {}} />
        ))}
      </div>
    );
  }
  if (section === "ask") {
    return (
      <div className="shell-ask">
        <input className="shell-ask-input" value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") searchMy(q).then(setMy).catch(() => {}); }}
          placeholder="检索台：输入词并回车（真实检索我的馆藏）" />
        {my && (
          <div className="shell-ask-results">
            <p className="catalog-no">{my.works.length} 作品 · {my.reviews.length} 书评 · {my.memories.length} 记忆</p>
            {my.works.slice(0, 12).map((w) => <div key={w.id} className="shell-ask-row">{w.title}</div>)}
            {my.memories.slice(0, 6).map((m) => <div key={m.id} className="shell-ask-row muted">{m.summary}</div>)}
          </div>
        )}
      </div>
    );
  }
  if (section === "gallery") return <MemoryGallery />;
  if (section === "characters") return <CharacterWall />;
  if (section === "voice") return <VoiceGraphView />;
  return (
    <div className="shell-settings">
      <h2 className="tsm-heading" style={{ fontSize: 20 }}>管理室</h2>
      <p className="catalog-no">设置 · 数据 · 备份</p>
      <p>（探索版仅示意，完整设置见经典三栏）</p>
    </div>
  );
}

/* ================= A：卡片抽屉导航 ================= */
export function ShellA() {
  const [section, setSection] = useState("library");
  return (
    <div className="shell-a" data-shell="a">
      <nav className="shell-a-cabinet">
        {SECTIONS.map((s, i) => (
          <button key={s.key}
            className={"shell-a-drawer" + (section === s.key ? " shell-a-open" : "")}
            onClick={() => setSection(s.key)} title={s.label}>
            <span className="shell-a-tab">{String(i + 1).padStart(2, "0")}</span>
            <span className="shell-a-label">{s.label}</span>
          </button>
        ))}
      </nav>
      <aside className="shell-a-drawer-index">
        <span className="catalog-no">抽屉 · {String(SECTIONS.findIndex((x) => x.key === section) + 1).padStart(2, "0")}</span>
        <h3 className="tsm-heading">{SECTIONS.find((x) => x.key === section).label}</h3>
        <div className="shell-a-rule" />
        <p className="shell-a-desc">此抽屉收藏着{section === "library" ? "已入库作品索引" : section === "gallery" ? "按年份排列的记忆" : "相关馆藏"}</p>
      </aside>
      <main className="shell-a-main"><ShellContent section={section} /></main>
    </div>
  );
}

/* ================= B：书脊索引栏 ================= */
export function ShellB() {
  const [section, setSection] = useState("library");
  return (
    <div className="shell-b" data-shell="b">
      <nav className="shell-b-spines">
        {SECTIONS.map((s) => (
          <button key={s.key}
            className={"shell-b-spine" + (section === s.key ? " shell-b-active" : "")}
            onClick={() => setSection(s.key)} title={s.label}>
            <span className="shell-b-text">{s.label}</span>
            <span className="shell-b-no">{String(SECTIONS.findIndex((x) => x.key === s.key) + 1).padStart(2, "0")}</span>
          </button>
        ))}
        <span className="shell-b-board" />
      </nav>
      <main className="shell-b-main"><ShellContent section={section} /></main>
    </div>
  );
}

/* ================= C：非对称档案室 ================= */
export function ShellC() {
  const [section, setSection] = useState("library");
  return (
    <div className="shell-c" data-shell="c">
      <nav className="shell-c-rail">
        {SECTIONS.map((s, i) => (
          <button key={s.key}
            className={"shell-c-nav" + (section === s.key ? " shell-c-active" : "")}
            onClick={() => setSection(s.key)}>
            <span className="shell-c-no">{String(i + 1).padStart(2, "0")}</span>
            <span>{s.label}</span>
          </button>
        ))}
      </nav>
      <div className="shell-c-room" data-room={section}>
        <ShellContent section={section} />
      </div>
    </div>
  );
}

/* ================= 外壳开关 ================= */
export function ShellSwitcher({ value, onChange }) {
  return (
    <div className="shell-switcher" data-testid="shell-switcher">
      {SHELL_CONCEPTS.map((c) => (
        <button key={c.key} data-shell-key={c.key} onClick={() => onChange(c.key)}
          style={{
            color: value === c.key ? "#fff" : "var(--text-secondary)",
            backgroundColor: value === c.key ? "var(--accent)" : "var(--accent-soft)",
          }}>{c.label}</button>
      ))}
    </div>
  );
}
