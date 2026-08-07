// 标签编辑弹层：单条（右键菜单）与批量（批量操作栏）共用。
// 收集标签串 + 操作方式（添加/替换/移除）。
import React, { useState } from "react";

export default function TagEditModal({ title, onApply, onClose }) {
  const [value, setValue] = useState("");
  const [action, setAction] = useState("add");
  const [saving, setSaving] = useState(false);

  async function submit(e) {
    e.preventDefault();
    const tags = value.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
    if (tags.length === 0) return;
    setSaving(true);
    try {
      await onApply(tags, action);
      onClose();
    } catch (err) {
      setSaving(false);
      /* 错误由调用方 toast 提示后仍关闭 */
      onClose();
    }
  }

  return (
    <div className="fixed inset-0 z-[58] flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(10,12,20,0.4)" }} onClick={onClose}>
      <form className="desk-askbar p-5 w-full max-w-sm"
        onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3 className="text-sm font-medium mb-3" style={{ color: "var(--text)" }}>{title}</h3>
        <input autoFocus value={value} onChange={(e) => setValue(e.target.value)}
          placeholder="标签，用逗号分隔（如：动漫, 恋爱）"
          className="tsm-input w-full border rounded px-2.5 py-2 text-sm mb-3" />
        <div className="flex gap-2 mb-4">
          {[["add", "添加"], ["set", "替换"], ["remove", "移除"]].map(([k, label]) => (
            <button key={k} type="button" onClick={() => setAction(k)}
              className="px-3 py-1.5 rounded-xl text-xs"
              style={{ backgroundColor: action === k ? "var(--accent)" : "var(--accent-soft)",
                color: action === k ? "#fff" : "var(--accent)" }}>
              {label}
            </button>
          ))}
        </div>
        <div className="flex gap-2 justify-end">
          <button type="button" onClick={onClose}
            className="px-3 py-1.5 rounded-xl text-sm"
            style={{ color: "var(--text-secondary)" }}>取消</button>
          <button type="submit" disabled={saving}
            className="px-4 py-1.5 rounded-xl text-sm font-medium disabled:opacity-40"
            style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
            {saving ? "应用中…" : "应用"}
          </button>
        </div>
      </form>
    </div>
  );
}
