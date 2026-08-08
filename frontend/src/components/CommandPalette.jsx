// 命令面板（Command Palette，ADR 0031）
// Ctrl/Cmd+K 呼出；输入实时过滤；↑↓ 选择、Enter 执行、Esc 关闭。
// 视觉严格走主题 token（surface-1 表面 / panel-border / shadow-lg / accent），
// 分组标题复用 Overview 的"区段标签"排版，不另起一套风格。
import React, { useEffect, useMemo, useRef, useState } from "react";
import { buildCommands, matchCommand, GROUP_ORDER } from "../commands.js";

const GROUP_CAP = { 条目: 8, 动作: 100, 主题: 100, 标签: 8 };

export default function CommandPalette({ open, onClose, ctx }) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef(null);

  // 全部命令（构建一次；内容搜索的 items 由 ctx 提供）
  const allCommands = useMemo(() => (ctx ? buildCommands(ctx) : []), [ctx]);

  // 过滤 + 分组 + 打平（键盘导航用扁平索引）
  const { groups, flat } = useMemo(() => {
    const q = query.trim();
    const visible = allCommands.filter((c) => matchCommand(c, q));
    const byGroup = {};
    for (const c of visible) {
      if (q && c.group === "条目") { /* 有查询才展示条目（条目量大） */ }
      if (!q && c.group === "条目") continue; // 空查询不展示条目，避免刷屏
      const cap = GROUP_CAP[c.group] ?? 100;
      const list = byGroup[c.group] || (byGroup[c.group] = []);
      if (list.length < cap) list.push(c);
    }
    const ordered = GROUP_ORDER.filter((g) => (byGroup[g] || []).length > 0);
    const groups = ordered.map((g) => ({ group: g, items: byGroup[g] }));
    const flat = [];
    for (const g of groups) for (const c of g.items) flat.push(c);
    return { groups, flat };
  }, [allCommands, query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIndex(0);
      setTimeout(() => inputRef.current?.focus(), 20);
    }
  }, [open]);

  // 选择态收敛到有效范围（过滤后候选数变化时）
  useEffect(() => { setActiveIndex((i) => (flat.length ? Math.min(i, flat.length - 1) : 0)); }, [flat]);

  if (!open) return null;

  function run(cmd) {
    try { cmd.run(); } finally { onClose(); }
  }

  function onKeyDown(e) {
    if (e.key === "ArrowDown") { e.preventDefault(); setActiveIndex((i) => Math.min(i + 1, flat.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActiveIndex((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); if (flat[activeIndex]) run(flat[activeIndex]); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  }

  let cursor = 0;
  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center"
      style={{ backgroundColor: "rgba(8,10,18,0.45)", paddingTop: "18vh" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="w-full max-w-xl rounded-2xl border overflow-hidden"
        style={{ backgroundColor: "var(--surface-1)", borderColor: "var(--panel-border)", boxShadow: "var(--shadow-lg)" }}>
        {/* 输入框 */}
        <div className="flex items-center gap-2 px-4 py-3 border-b" style={{ borderColor: "var(--panel-border)" }}>
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2"
            className="shrink-0" style={{ color: "var(--text-secondary)" }}>
            <circle cx="11" cy="11" r="7" /><path d="M21 21l-4.35-4.35" />
          </svg>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setActiveIndex(0); }}
            onKeyDown={onKeyDown}
            placeholder="搜索资料 / 输入命令…（↑↓ 选择 · Enter 执行 · Esc 关闭）"
            className="flex-1 bg-transparent outline-none text-sm min-w-0"
            style={{ color: "var(--text)" }}
          />
          <span className="text-[10px] px-1.5 py-0.5 rounded shrink-0"
            style={{ color: "var(--text-secondary)", backgroundColor: "var(--surface-2)" }}>Ctrl K</span>
        </div>

        {/* 结果列表（独立滚动，不引入页面滚动，ADR 0028/0031） */}
        <div className="max-h-[46vh] overflow-y-auto p-2" onMouseDown={(e) => e.stopPropagation()}>
          {flat.length === 0 ? (
            <div className="px-3 py-8 text-center text-sm" style={{ color: "var(--text-secondary)" }}>
              {query.trim() ? "没有匹配的命令或资料。" : "输入内容搜索或命令…"}
            </div>
          ) : (
            groups.map(({ group, items }) => (
              <div key={group} className="mb-1.5">
                <div className="px-2 py-1 text-[11px] tracking-wider" style={{ color: "var(--text-secondary)" }}>
                  {group}
                </div>
                {items.map((c) => {
                  const idx = cursor++;
                  const active = idx === activeIndex;
                  return (
                    <button
                      key={c.id}
                      type="button"
                      onMouseEnter={() => setActiveIndex(idx)}
                      onClick={() => run(c)}
                      className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left text-[13px]"
                      style={{
                        color: "var(--text)",
                        backgroundColor: active ? "var(--surface-2)" : "transparent",
                      }}>
                      <span className="w-5 shrink-0 text-center text-[12px]" style={{ color: active ? "var(--accent)" : "var(--text-secondary)" }}>
                        {c.icon || ""}
                      </span>
                      <span className="flex-1 min-w-0 truncate">{c.title}</span>
                      {active && <span className="text-[10px]" style={{ color: "var(--accent)" }}>↵</span>}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
