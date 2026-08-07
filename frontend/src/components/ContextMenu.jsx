// 通用右键上下文菜单：定位视口内 + 点击外部/Esc 关闭。复用主题 token。
import React, { useEffect, useRef, useState } from "react";

export default function ContextMenu({ x, y, items, onClose }) {
  const ref = useRef(null);
  const [pos, setPos] = useState({ x, y });

  useEffect(() => {
    if (ref.current) {
      const r = ref.current.getBoundingClientRect();
      const nx = Math.min(x, (window.innerWidth || 0) - r.width - 8);
      const ny = Math.min(y, (window.innerHeight || 0) - r.height - 8);
      setPos({ x: Math.max(8, nx), y: Math.max(8, ny) });
    }
  }, [x, y]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div className="fixed inset-0 z-[55]" onMouseDown={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }} />
      <div ref={ref} className="fixed z-[56] min-w-[168px] py-1.5" data-testid="context-menu"
        style={{
          left: pos.x, top: pos.y,
          backgroundColor: "var(--panel)",
          border: "1px solid var(--panel-border)",
          borderRadius: "var(--radius-md)",
          boxShadow: "var(--shadow-md)",
        }}>
        {items.map((it, i) =>
          it.divider ? (
            <div key={i} className="my-1 h-px" style={{ backgroundColor: "var(--panel-border)" }} />
          ) : (
            <button key={i}
              onClick={() => { onClose(); it.onClick?.(); }}
              className="w-full text-left px-3 py-1.5 text-sm hover:opacity-80"
              style={{ color: it.danger ? "var(--danger)" : "var(--text)" }}>
              {it.label}
            </button>
          )
        )}
      </div>
    </>
  );
}
