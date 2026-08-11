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
      {/* 顶栏：品牌（应用外壳一部分，固定不随内容滚动；ADR 0028） */}
      <header className="border-b px-5 py-3 flex items-center justify-between shrink-0"
        style={{
          backgroundColor: "var(--panel)",
          borderColor: "var(--panel-border)",
          zIndex: 30,
        }}>
        <div className="flex items-center gap-2">
          <span className="text-lg font-semibold tracking-wide" style={{ color: "var(--accent)" }}>
            紬
          </span>
          <span className="font-medium">Tsumugi</span>
        </div>
      </header>

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
