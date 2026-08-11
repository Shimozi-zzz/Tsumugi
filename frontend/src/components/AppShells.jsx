// 应用外壳 · 空间结构（ADR 0057/0059/0064/0065）
// 本轮定案（ADR 0059）：仅保留「经典三栏」与「C 非对称档案室」两个外壳。
// ADR 0064：ShellC 交互化（点卡开详情/检索可点/回廊接线）+ 外壳切换入设置。
// ADR 0065：ShellC 整合既有功能——书库三种浏览+筛选、管理室真实化（AI Provider/备份）、
//   命令面板 Ctrl+K（ShellC 作用域命令集）。
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchItems, searchMy, filePathToUrl, fetchCollections,
  exportBackup, importBackup, fetchImportStatus,
} from "../api.js";
import ArchiveCard from "./ArchiveCard.jsx";
import Bookshelf from "./Bookshelf.jsx";
import StatusGroupedList from "./StatusGroupedList.jsx";
import MemoryGallery from "./MemoryGallery.jsx";
import CharacterWall from "./CharacterWall.jsx";
import VoiceGraphView from "./VoiceGraphView.jsx";
import ItemDetailPanel from "./ItemDetailPanel.jsx";
import MemoryReviewModal from "./MemoryReviewModal.jsx";
import ProviderSettings from "./ProviderSettings.jsx";
import CommandPalette from "./CommandPalette.jsx";
import CoverAmbient from "./CoverAmbient.jsx";
import { WORK_TYPES, WORK_TYPE_LABEL } from "./ui.jsx";
import { THEMES } from "../themes.js";
import { toast } from "../toast.js";

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

/* ================= 书库房间（ADR 0065：三视图 + 类型筛选 + 库内搜索） ================= */
function ShellLibrary({ onOpenWork }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [libView, setLibView] = useState(() => {
    try { return localStorage.getItem("tsumugi-shell-lib-view") || "grid"; } catch { return "grid"; }
  });
  const [libQuery, setLibQuery] = useState("");
  const [activeWorkType, setActiveWorkType] = useState(null);
  const [statusMap, setStatusMap] = useState({});

  useEffect(() => {
    let c = false;
    fetchItems({ limit: 48 })
      .then((d) => { if (!c) { setItems(d.items || []); setLoading(false); } })
      .catch(() => { if (!c) setLoading(false); });
    fetchCollections()
      .then((rows) => {
        const m = {};
        for (const r of rows) if (r.status) m[r.item_id] = r.status;
        setStatusMap(m);
      })
      .catch(() => {});
    return () => { c = true; };
  }, []);

  useEffect(() => {
    try { localStorage.setItem("tsumugi-shell-lib-view", libView); } catch { /* ignore */ }
  }, [libView]);

  const workTypeOptions = WORK_TYPES.filter((t) => items.some((it) => it.work_type === t));
  const filtered = items.filter((it) => {
    if (activeWorkType && it.work_type !== activeWorkType) return false;
    if (!libQuery.trim()) return true;
    const q = libQuery.trim().toLowerCase();
    return (it.title || "").toLowerCase().includes(q) || (it.content || "").toLowerCase().includes(q);
  });

  return (
    <div className="flex flex-col min-h-0 h-full">
      {/* 工具栏：视图切换 + 库内搜索 */}
      <div className="flex items-center gap-2 mb-3 flex-wrap shrink-0">
        <div className="flex items-center gap-0.5 rounded-full px-1 py-0.5"
          style={{ backgroundColor: "var(--input-bg)", border: "1px solid var(--input-border)" }}>
          <button onClick={() => setLibView("grid")} title="网格视图"
            className="px-2 py-1 rounded-full text-[11px]"
            style={{ backgroundColor: libView === "grid" ? "var(--accent)" : "transparent",
              color: libView === "grid" ? "#fff" : "var(--text-secondary)" }}>▦</button>
          <button onClick={() => setLibView("shelf")} title="书架视图"
            className="px-2 py-1 rounded-full text-[11px]"
            style={{ backgroundColor: libView === "shelf" ? "var(--accent)" : "transparent",
              color: libView === "shelf" ? "#fff" : "var(--text-secondary)" }}>▤</button>
          <button onClick={() => setLibView("list")} title="分组列表"
            className="px-2 py-1 rounded-full text-[11px]"
            style={{ backgroundColor: libView === "list" ? "var(--accent)" : "transparent",
              color: libView === "list" ? "#fff" : "var(--text-secondary)" }}>☰</button>
        </div>
        <div className="flex items-center gap-2 rounded-full px-3.5 py-2 w-56"
          style={{ backgroundColor: "var(--input-bg)", border: "1px solid var(--input-border)" }}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2"
            className="shrink-0" style={{ color: "var(--text-secondary)" }}>
            <circle cx="11" cy="11" r="7" /><path d="M21 21l-4.35-4.35" />
          </svg>
          <input value={libQuery} onChange={(e) => setLibQuery(e.target.value)}
            placeholder="查找书库内容…"
            className="flex-1 bg-transparent outline-none text-sm min-w-0"
            style={{ color: "var(--text)" }} />
        </div>
      </div>

      {/* 类型筛选（有该类型数据时显示） */}
      {workTypeOptions.length > 0 && (
        <div className="flex items-center gap-1.5 mb-3 flex-wrap shrink-0">
          <button onClick={() => setActiveWorkType(null)}
            className="px-3 py-1 rounded-full text-xs transition-colors"
            style={{ color: activeWorkType === null ? "#fff" : "var(--text-secondary)",
              backgroundColor: activeWorkType === null ? "var(--accent)" : "var(--accent-soft)" }}>
            全部类型
          </button>
          {workTypeOptions.map((t) => (
            <button key={t} onClick={() => setActiveWorkType(activeWorkType === t ? null : t)}
              className="px-3 py-1 rounded-full text-xs transition-colors"
              style={{ color: activeWorkType === t ? "#fff" : "var(--text-secondary)",
                backgroundColor: activeWorkType === t ? "var(--accent)" : "var(--accent-soft)" }}>
              {WORK_TYPE_LABEL[t]}
            </button>
          ))}
        </div>
      )}

      {/* 内容区：网格 / 书架 / 分组列表 */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {loading ? (
          <div className="text-sm py-10 text-center" style={{ color: "var(--text-secondary)" }}>加载中…</div>
        ) : filtered.length === 0 ? (
          <div className="text-sm py-10 text-center" style={{ color: "var(--text-secondary)" }}>
            {items.length === 0 ? "暂无资料，去「检索台」搜索并收藏一部作品吧。" : "没有匹配的书库内容。"}
          </div>
        ) : libView === "shelf" ? (
          <Bookshelf items={filtered} coverOf={coverOf} onOpenItem={(it) => onOpenWork(it.id)} />
        ) : libView === "list" ? (
          <StatusGroupedList items={filtered} statusOf={statusMap} selectedId={null}
            onSelect={(id) => onOpenWork(id)} />
        ) : (
          <div className="shell-grid">
            {filtered.map((it) => (
              <CoverAmbient key={it.id} src={coverOf(it)} alphaFactor={0.6}>
                <ArchiveCard it={it} cover={coverOf(it)} onOpen={() => onOpenWork(it.id)} />
              </CoverAmbient>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ================= 管理室：数据备份（ADR 0065，复用既有 API） ================= */
function ShellBackup() {
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);

  async function doExport() {
    setBusy(true);
    try {
      const data = await exportBackup();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const ts = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      a.href = url; a.download = `tsumugi-backup-${ts}.json`; a.click();
      URL.revokeObjectURL(url);
      toast.success(`已导出 ${(data.data?.items || []).length} 个条目`);
    } catch (err) { toast.error(err.message); }
    finally { setBusy(false); }
  }

  async function doImport(file) {
    if (!file) return;
    setBusy(true);
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const { job_id } = await importBackup(data);
      for (let i = 0; i < 600; i++) {
        await new Promise((r) => setTimeout(r, 500));
        const st = await fetchImportStatus(job_id);
        if (st.state === "done") { toast.success(st.message || "导入完成"); setBusy(false); return; }
        if (st.state === "error") { throw new Error(st.message || "导入失败"); }
      }
      throw new Error("导入超时");
    } catch (err) {
      setBusy(false);
      toast.error(err.message || "导入失败（文件格式是否正确？）");
    }
  }

  return (
    <div className="desk-askbar p-5">
      <h3 className="text-sm font-medium mb-1">数据备份</h3>
      <p className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
        导出 / 导入 JSON（幂等合并，后台重建向量）
      </p>
      <div className="flex items-center gap-2">
        <button onClick={doExport} disabled={busy}
          className="px-3 py-1.5 rounded-xl text-sm disabled:opacity-40"
          style={{ backgroundColor: "var(--accent)", color: "#fff" }}>{busy ? "处理中…" : "导出备份"}</button>
        <button onClick={() => fileRef.current?.click()} disabled={busy}
          className="px-3 py-1.5 rounded-xl text-sm disabled:opacity-40"
          style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>导入备份</button>
        <input ref={fileRef} type="file" accept="application/json,.json" className="hidden"
          onChange={(e) => { doImport(e.target.files?.[0]); e.target.value = ""; }} />
      </div>
    </div>
  );
}

/* ---------- 房间内容渲染器（ShellC 共用；交互经回调上抛给 ShellC） ---------- */
function ShellContent({ section, onOpenWork, onOpenReview, voiceFocus, onOpenVoice, shellValue, onShellChange }) {
  const [q, setQ] = useState("");
  const [my, setMy] = useState(null);

  if (section === "library") return <ShellLibrary onOpenWork={onOpenWork} />;
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
  // 管理室：真实设置（ADR 0064/0065：外壳切换 + AI Provider + 数据备份）
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
        <div className="desk-askbar p-5">
          <h3 className="text-sm font-medium mb-1">AI Provider</h3>
          <p className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
            可选扩展：没有 AI，Tsumugi 核心功能也完整
          </p>
          <ProviderSettings />
        </div>
        <ShellBackup />
      </div>
    </div>
  );
}

/* ================= C：非对称档案室 ================= */
export function ShellC({ shellValue = "c", onShellChange = () => {}, setTheme = () => {} }) {
  const [section, setSection] = useState("library");
  const [detailId, setDetailId] = useState(null);   // 详情弹层
  const [voiceFocus, setVoiceFocus] = useState(null);
  const [reviewModal, setReviewModal] = useState(null); // { itemId, sourceRef, memory }
  const [cmdOpen, setCmdOpen] = useState(false);
  const [paletteItems, setPaletteItems] = useState([]);

  useEffect(() => {
    fetchItems({ limit: 48 }).then((d) => setPaletteItems(d.items || [])).catch(() => {});
  }, []);

  // Ctrl/Cmd+K 命令面板（ADR 0065）
  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const openWork = (id) => setDetailId(id);
  const openReview = (itemId, sourceRef, memory) => setReviewModal({ itemId, sourceRef, memory });

  // ShellC 作用域命令集（复用 CommandPalette，ADR 0065）
  const shellCommands = useMemo(() => {
    const cmds = [
      { id: "open-library", group: "动作", title: "书库", icon: "▦", keywords: ["书库", "library", "书架", "收藏"], run: () => setSection("library") },
      { id: "open-ask", group: "动作", title: "检索台", icon: "⌕", keywords: ["检索台", "搜索", "问答", "ask", "聊天"], run: () => setSection("ask") },
      { id: "open-memories", group: "动作", title: "记忆回廊", icon: "◈", keywords: ["记忆回廊", "记忆", "回忆", "回廊", "memory", "gallery"], run: () => setSection("gallery") },
      { id: "open-characters", group: "动作", title: "人物馆", icon: "◉", keywords: ["人物馆", "角色", "characters", "图鉴"], run: () => setSection("characters") },
      { id: "open-voice", group: "动作", title: "关系厅", icon: "◉", keywords: ["关系厅", "声优", "图谱", "voice", "配音"], run: () => setSection("voice") },
      { id: "open-settings", group: "动作", title: "管理室", icon: "⚙", keywords: ["管理室", "设置", "settings", "配置"], run: () => setSection("settings") },
    ];
    for (const t of THEMES) {
      cmds.push({ id: `theme-${t.key}`, group: "主题", title: `切换主题：${t.label}`, icon: "◐", keywords: ["主题", "theme", t.label], run: () => setTheme(t.key) });
    }
    for (const it of paletteItems) {
      cmds.push({ id: `item-${it.id}`, group: "条目", title: it.title, icon: it.type === "note" ? "✎" : "▦", keywords: [it.title, it.source || "", it.type, it.work_type || ""], run: () => openWork(it.id) });
    }
    return cmds;
  }, [paletteItems, setTheme]);

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

      {/* 作品详情弹层（点书库卡片 / 回廊 / 人物馆 / 关系厅 / 命令面板 → 打开作品档案） */}
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

      {/* 命令面板（Ctrl/Cmd+K） */}
      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} commands={shellCommands} />
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
