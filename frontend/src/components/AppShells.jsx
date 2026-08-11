// 应用外壳 · 空间结构（ADR 0057/0059/0064）
// 本轮定案（ADR 0059）：仅保留「经典三栏」与「C 非对称档案室」两个外壳。
// 2026-08-11（ADR 0064）：C 非对称档案室**交互化**——书库点卡开详情弹层、
// 检索台结果可点开书评/记忆、回廊/人物馆/关系厅接线；外壳切换入口移入
// 设置（管理室），移除右下角浮动开关。沿用编目抽屉配色/字体/编号（ADR 0056）。
import React, { useEffect, useState } from "react";
import { fetchItems, searchMy, filePathToUrl } from "../api.js";
import ArchiveCard from "./ArchiveCard.jsx";
import MemoryGallery from "./MemoryGallery.jsx";
import CharacterWall from "./CharacterWall.jsx";
import VoiceGraphView from "./VoiceGraphView.jsx";
import ItemDetailPanel from "./ItemDetailPanel.jsx";
import MemoryReviewModal from "./MemoryReviewModal.jsx";

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

/* ---------- 房间内容渲染器（ShellC 共用；交互经回调上抛给 ShellC） ---------- */
function ShellContent({ section, onOpenWork, onOpenReview, voiceFocus, onOpenVoice, shellValue, onShellChange }) {
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
          <ArchiveCard key={it.id} it={it} cover={coverOf(it)} onOpen={() => onOpenWork(it.id)} />
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
            {my.works.slice(0, 12).map((w) => (
              <button key={w.id} className="shell-ask-row" title="打开这部作品"
                onClick={() => onOpenWork(w.id)}>{w.title}</button>
            ))}
            {my.reviews.slice(0, 6).map((r) => (
              <button key={r.id} className="shell-ask-row" title="打开这篇书评"
                onClick={() => onOpenReview(r.item_id, r.id, null)}>{r.title || r.content}</button>
            ))}
            {my.memories.slice(0, 6).map((m) => (
              <button key={m.id} className="shell-ask-row muted" title="打开这条记忆"
                onClick={() => onOpenReview(m.item_id, m.source_ref, m.source_type === "review" ? null : m)}>{m.summary}</button>
            ))}
          </div>
        )}
      </div>
    );
  }
  if (section === "gallery") return <MemoryGallery onOpenWork={onOpenWork} />;
  if (section === "characters") return <CharacterWall onOpenWork={onOpenWork} onOpenVoice={onOpenVoice} />;
  if (section === "voice") return <VoiceGraphView focusActor={voiceFocus} onOpenWork={onOpenWork} />;
  // 管理室：真实设置入口（ADR 0064：外壳切换入设置）
  return (
    <div className="shell-settings">
      <h2 className="tsm-heading" style={{ fontSize: 20 }}>管理室</h2>
      <p className="catalog-no">设置 · 数据 · 备份</p>
      <div className="mt-4 space-y-4">
        <div className="desk-askbar p-5">
          <h3 className="text-sm font-medium mb-1">应用外壳</h3>
          <p className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
            图书馆的空间结构（经典三栏 / C 非对称档案室）
          </p>
          <ShellSwitcher value={shellValue} onChange={onShellChange} />
        </div>
        <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
          数据管理（导入 / 导出 / 备份）请在「经典三栏」外壳的管理室完成。
        </p>
      </div>
    </div>
  );
}

/* ================= C：非对称档案室 ================= */
export function ShellC({ shellValue = "c", onShellChange = () => {} }) {
  const [section, setSection] = useState("library");
  const [detailId, setDetailId] = useState(null);   // 详情弹层
  const [voiceFocus, setVoiceFocus] = useState(null);
  const [reviewModal, setReviewModal] = useState(null); // { itemId, sourceRef, memory }

  const openWork = (id) => setDetailId(id);
  const openReview = (itemId, sourceRef, memory) => setReviewModal({ itemId, sourceRef, memory });

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
        <ShellContent section={section}
          onOpenWork={openWork} onOpenReview={openReview}
          voiceFocus={voiceFocus}
          onOpenVoice={(a) => { setVoiceFocus(a); setSection("voice"); }}
          shellValue={shellValue} onShellChange={onShellChange} />
      </div>

      {/* 作品详情弹层（点书库卡片 / 回廊 / 人物馆 / 关系厅 → 打开作品档案） */}
      {detailId != null && (
        <div className="fixed inset-0 z-50 overflow-y-auto"
          style={{ backgroundColor: "rgba(20, 14, 8, 0.45)" }}
          onClick={(e) => { if (e.target === e.currentTarget) setDetailId(null); }}>
          <div className="min-h-full flex justify-center p-4 sm:p-8">
            <div className="w-full max-w-4xl my-auto"
              style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-lg)" }}>
              <div className="flex items-center justify-between px-5 py-3 border-b"
                style={{ borderColor: "var(--panel-border)" }}>
                <span className="tsm-heading text-sm" style={{ color: "var(--text)" }}>作品档案</span>
                <button onClick={() => setDetailId(null)} title="关闭" className="text-sm px-1"
                  style={{ color: "var(--text-secondary)" }}>✕</button>
              </div>
              <div className="p-5">
                <ItemDetailPanel itemId={detailId} />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 书评 / 记忆只读弹层（检索台命中点开） */}
      {reviewModal && (
        <MemoryReviewModal itemId={reviewModal.itemId} sourceRef={reviewModal.sourceRef}
          memory={reviewModal.memory} onClose={() => setReviewModal(null)} />
      )}
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
