// 状态分组列表（ADR 0029 第三种浏览模式）
// 按追番状态（想看/在看/看完/搁置/弃坑 + 未收藏）分组，每组标题带数量角标、
// 可折叠展开；主从视图的"主"：点击行 → 右侧详情立即更新。
import React, { useState } from "react";
import { TagCapsule } from "./ui.jsx";

export const STATUS_GROUPS = ["想看", "在看", "看完", "搁置", "弃坑", "未收藏"];

function groupKey(status) {
  return status || "未收藏";
}

export default function StatusGroupedList({ items, statusOf, selectedId, onSelect, className = "" }) {
  const [collapsed, setCollapsed] = useState(new Set());

  const groups = {};
  for (const it of items || []) {
    const key = groupKey(statusOf?.[it.id]);
    (groups[key] = groups[key] || []).push(it);
  }
  const ordered = STATUS_GROUPS.filter((g) => (groups[g] || []).length > 0);

  const toggle = (g) => setCollapsed((prev) => {
    const next = new Set(prev);
    if (next.has(g)) next.delete(g); else next.add(g);
    return next;
  });

  if (items && items.length === 0) {
    return <div className={"text-sm text-center py-8 " + className} style={{ color: "var(--text-secondary)" }}>暂无资料。</div>;
  }

  return (
    <div className={"flex flex-col gap-3 " + className}>
      {ordered.map((g) => {
        const list = groups[g];
        const isCollapsed = collapsed.has(g);
        return (
          <section key={g}>
            <button
              type="button"
              onClick={() => toggle(g)}
              className="w-full flex items-center gap-2 py-1.5 mb-0.5 text-left rounded-lg"
              style={{ color: "var(--text)" }}
            >
              <span className="text-[11px] w-3 shrink-0" style={{ color: "var(--accent)" }}>
                {isCollapsed ? "▸" : "▾"}
              </span>
              <span className="text-[12px] font-medium tracking-wider" style={{ color: "var(--text-secondary)" }}>
                {g}
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded-full"
                style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
                {list.length}
              </span>
            </button>
            {!isCollapsed && (
              <ul className="space-y-1">
                {list.map((it) => {
                  const active = it.id === selectedId;
                  return (
                    <li key={it.id}>
                      <button
                        type="button"
                        onClick={() => onSelect?.(it.id)}
                        className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-left transition-colors"
                        style={{
                          color: "var(--text)",
                          backgroundColor: active ? "var(--accent-soft)" : "transparent",
                          border: "1px solid " + (active ? "var(--accent)" : "transparent"),
                        }}
                      >
                        <span className="text-[11px] w-8 shrink-0"
                          style={{ color: it.type === "image" ? "var(--text-secondary)" : "var(--accent)" }}>
                          {it.type === "note" ? "✎" : it.type === "image" ? "🖼" : it.source === "local" ? "▣" : it.source}
                        </span>
                        <span className="flex-1 min-w-0 truncate text-[13px]">{it.title}</span>
                        {it.type === "note" && it.chunks_count != null && (
                          <TagCapsule text={`${it.chunks_count} 块`} muted />
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}
