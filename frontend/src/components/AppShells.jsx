// 应用外壳 · 空间结构（ADR 0057/0059）
// 本轮定案（ADR 0059）：仅保留「经典三栏」与「C 非对称档案室」两个外壳；
// A 卡片抽屉、B 书脊索引已移除。沿用编目抽屉配色/字体/编号（ADR 0056）。
// C：不同页面房间格局不同（宽度/偏移/错落非对称）。真实数据渲染。
import React, { useEffect, useState } from "react";
import { fetchItems, searchMy, filePathToUrl } from "../api.js";
import ArchiveCard from "./ArchiveCard.jsx";
import MemoryGallery from "./MemoryGallery.jsx";
import CharacterWall from "./CharacterWall.jsx";
import VoiceGraphView from "./VoiceGraphView.jsx";

export const SHELL_CONCEPTS = [
  { key: "classic", label: "经典三栏" },
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
