// Toast 提示宿主：右下角堆叠，自动消失；样式复用主题 token（ADR 0021）
import React, { useEffect, useState } from "react";
import { subscribeToast } from "../toast.js";

const TYPE_COLOR = {
  success: "var(--ok)",
  error: "var(--danger)",
  info: "var(--accent)",
};

export default function ToastHost() {
  const [toasts, setToasts] = useState([]);
  useEffect(() => subscribeToast(setToasts), []);

  if (toasts.length === 0) return null;
  return (
    <div className="fixed bottom-5 right-5 z-[70] flex flex-col gap-2 items-end pointer-events-none">
      {toasts.map((t) => (
        <div key={t.id}
          className="pointer-events-auto flex items-center gap-2 px-3.5 py-2 text-sm max-w-xs"
          style={{
            backgroundColor: "var(--panel)",
            border: "1px solid var(--panel-border)",
            borderRadius: "var(--radius-md)",
            boxShadow: "var(--shadow-md)",
            color: "var(--text)",
            animation: "history-dropdown-in 0.18s cubic-bezier(0.16,1,0.3,1)",
          }}>
          <span className="w-2 h-2 rounded-full shrink-0"
            style={{ backgroundColor: TYPE_COLOR[t.type] || "var(--accent)" }} />
          <span className="leading-snug">{t.message}</span>
        </div>
      ))}
    </div>
  );
}
