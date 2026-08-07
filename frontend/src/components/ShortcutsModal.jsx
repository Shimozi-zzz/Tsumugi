// 快捷键说明弹层（按 ? 或点击帮助按钮打开，保证可发现）
import React from "react";

const SHORTCUTS = [
  { keys: ["/"], desc: "聚焦搜索框并提问" },
  { keys: ["Ctrl+K"], desc: "聚焦搜索框并提问" },
  { keys: ["Esc"], desc: "关闭弹层 / 详情 / 右键菜单 / 退出选择模式" },
  { keys: ["?"], desc: "显示 / 隐藏本快捷键列表" },
];

export default function ShortcutsModal({ onClose }) {
  return (
    <div className="fixed inset-0 z-[58] flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(10,12,20,0.4)" }} onClick={onClose}>
      <div className="desk-askbar p-5 w-full max-w-sm"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium" style={{ color: "var(--text)" }}>键盘快捷键</h3>
          <button onClick={onClose} className="text-sm px-2 py-0.5 rounded-lg"
            style={{ color: "var(--text-secondary)" }}>✕</button>
        </div>
        <ul className="space-y-2">
          {SHORTCUTS.map((s, i) => (
            <li key={i} className="flex items-center justify-between text-sm">
              <span style={{ color: "var(--text-secondary)" }}>{s.desc}</span>
              <span className="px-2 py-0.5 rounded-md text-xs font-mono"
                style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
                {s.keys.join(" / ")}
              </span>
            </li>
          ))}
        </ul>
        <p className="text-xs mt-3" style={{ color: "var(--text-secondary)" }}>
          方向键在网格/书架中的条目导航暂未实现（见 ADR 0021）。
        </p>
      </div>
    </div>
  );
}
