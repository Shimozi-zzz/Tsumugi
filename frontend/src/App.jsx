import React, { useEffect, useState } from "react";
import { fetchItems, fetchTags } from "./api.js";
import { loadTheme, applyTheme } from "./themes.js";
import DesktopView from "./components/DesktopView.jsx";

const PAGE_SIZE = 100;

// 背景设置持久化
const BG_STORAGE_KEY = "tsumugi-bg";
// 文字涂鸦设置持久化
const TEXT_OVERLAYS_KEY = "tsumugi-text-overlays";

function loadBg() {
  try {
    const raw = localStorage.getItem(BG_STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return { image: null, opacity: 0.5, blur: 20 };
}

function loadTextOverlays() {
  try {
    const raw = localStorage.getItem(TEXT_OVERLAYS_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return []; // [{ id, text, x, y, size, color }]
}

export default function App() {
  const [theme, setTheme] = useState(() => loadTheme());
  const [bg, setBg] = useState(() => loadBg());
  const [textOverlays, setTextOverlays] = useState(() => loadTextOverlays());
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [allTags, setAllTags] = useState([]);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const updateBg = (patch) => {
    setBg((prev) => {
      const next = { ...prev, ...patch };
      try { localStorage.setItem(BG_STORAGE_KEY, JSON.stringify(next)); } catch { /* 超限时忽略 */ }
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
    <div className="min-h-screen app-root"
      style={{ backgroundColor: "var(--bg)", color: "var(--text)" }}>
      {/* 用户自定义背景图层 */}
      {bg.image && (
        <div className="bg-custom-layer" aria-hidden="true"
          style={{
            backgroundImage: `url(${bg.image})`,
            backgroundSize: "cover",
            backgroundPosition: "center",
            opacity: bg.opacity,
            filter: `blur(${bg.blur}px)`,
          }} />
      )}

      {/* 顶栏：品牌 */}
      <header className="border-b px-5 py-3 flex items-center justify-between"
        style={{
          backgroundColor: "var(--panel)",
          borderColor: "var(--panel-border)",
          backdropFilter: "blur(18px) saturate(150%)",
          WebkitBackdropFilter: "blur(18px) saturate(150%)",
          position: "sticky",
          top: 0,
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
        bg={bg}
        updateBg={updateBg}
        theme={theme}
        setTheme={setTheme}
        textOverlays={textOverlays}
        updateTextOverlays={updateTextOverlays}
      />
    </div>
  );
}
