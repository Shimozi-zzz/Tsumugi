import React, { useEffect, useState } from "react";
import { fetchItems, fetchTags } from "./api.js";
import { loadTheme, loadCustom, applyTheme, saveCustom, loadStyleTheme, applyStyleTheme } from "./themes.js";
import DesktopView from "./components/DesktopView.jsx";

const PAGE_SIZE = 100;

// 文字涂鸦设置持久化
const TEXT_OVERLAYS_KEY = "tsumugi-text-overlays";

function loadTextOverlays() {
  try {
    const raw = localStorage.getItem(TEXT_OVERLAYS_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return []; // [{ id, text, x, y, size, color }]
}

// 自定义标题栏（Desktop Shell）：品牌 + 窗口控制；拖拽区与 no-drag 由 index.css 处理
function TitleBar() {
  const [maximized, setMaximized] = useState(false);
  useEffect(() => {
    const b = typeof window !== "undefined" ? window.tsumugiBridge?.window : null;
    b?.onMaximizedChange?.(setMaximized);
  }, []);
  const bridge = typeof window !== "undefined" ? window.tsumugiBridge?.window : null;
  const ctl = (dataWin, title, icon, onClick, danger) => (
    <button type="button" data-win={dataWin} title={title} aria-label={title}
      onClick={onClick}
      className={danger ? "win-ctl app-titlebar-close" : "win-ctl"}
      style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 46, height: "100%", border: "none", background: "transparent", color: danger ? "var(--danger)" : "var(--text-secondary)", cursor: "pointer", padding: 0 }}>
      {icon}
    </button>
  );
  return (
    <header className="app-titlebar shrink-0"
      style={{ height: 38, display: "flex", alignItems: "center", justifyContent: "space-between", background: "var(--panel)", borderBottom: "1px solid var(--panel-border)", paddingLeft: 12, flexShrink: 0, position: "relative", zIndex: 40 }}>
      <div className="flex items-center gap-2" style={{ pointerEvents: "none" }}>
        <span style={{ color: "var(--accent)", fontSize: 14, lineHeight: 1 }}>紬</span>
        <span style={{ fontSize: 12, color: "var(--text)", fontWeight: 600 }}>Tsumugi</span>
      </div>
      <div style={{ display: "flex", height: "100%" }}>
        {ctl("minimize", "最小化",
          <svg viewBox="0 0 10 10" width="10" height="10" style={{ display: "block" }}><path d="M0 5h10" stroke="currentColor" strokeWidth="1.2" /></svg>,
          () => bridge?.minimize?.())}
        {ctl("maximize", maximized ? "还原" : "最大化",
          maximized
            ? <svg viewBox="0 0 10 10" width="10" height="10" style={{ display: "block" }}><rect x="0" y="2" width="8" height="8" fill="none" stroke="currentColor" strokeWidth="1" /><path d="M2 0h8v8" fill="none" stroke="currentColor" strokeWidth="1" /></svg>
            : <svg viewBox="0 0 10 10" width="10" height="10" style={{ display: "block" }}><rect x="0" y="0" width="10" height="10" fill="none" stroke="currentColor" strokeWidth="1" /></svg>,
          () => bridge?.toggleMaximize?.())}
        {ctl("close", "关闭",
          <svg viewBox="0 0 10 10" width="10" height="10" style={{ display: "block" }}><path d="M0 0l10 10M10 0L0 10" stroke="currentColor" strokeWidth="1.2" /></svg>,
          () => bridge?.close?.(),
          true)}
      </div>
    </header>
  );
}

export default function App() {
  const [theme, setTheme] = useState(() => loadTheme());
  const [custom, setCustom] = useState(() => loadCustom());
  const [styleTheme, setStyleTheme] = useState(() => loadStyleTheme());
  const [textOverlays, setTextOverlays] = useState(() => loadTextOverlays());
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [allTags, setAllTags] = useState([]);

  useEffect(() => {
    applyTheme(theme, custom);
  }, [theme, custom]);

  useEffect(() => {
    applyStyleTheme(styleTheme);
  }, [styleTheme]);

  const updateCustom = (patch) => {
    setCustom((prev) => {
      const next = { ...prev, ...patch };
      saveCustom(next);
      return next;
    });
  };

  const updateTextOverlays = (next) => {
    setTextOverlays(next);
    try { localStorage.setItem(TEXT_OVERLAYS_KEY, JSON.stringify(next)); } catch { /* ignore */ }
  };

  const refresh = () => {
    fetchItems({ skip: 0, limit: PAGE_SIZE })
      .then((d) => { setItems(d.items); setTotal(d.total); })
      .catch(() => {});
    fetchTags().then(setAllTags).catch(() => {});
  };

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="app-root h-screen flex flex-col overflow-hidden"
      style={{ backgroundColor: "var(--bg)", color: "var(--text)" }}>
      <TitleBar />
      <DesktopView
        items={items}
        total={total}
        allTags={allTags}
        refresh={refresh}
        theme={theme}
        setTheme={setTheme}
        custom={custom}
        updateCustom={updateCustom}
        styleTheme={styleTheme}
        setStyleTheme={setStyleTheme}
        textOverlays={textOverlays}
        updateTextOverlays={updateTextOverlays}
      />
    </div>
  );
}
