// 命令面板（Command Palette，ADR 0031）
// Ctrl/Cmd+K 呼出；输入实时过滤；↑↓ 选择、Enter 执行、Esc 关闭。
// 视觉严格走主题 token（surface-1 表面 / panel-border / shadow-lg / accent），
// 分组标题复用 Overview 的"区段标签"排版，不另起一套风格。
import React, { useEffect, useMemo, useRef, useState } from "react";
import { buildCommands, matchCommand, GROUP_ORDER } from "../commands.js";

const GROUP_CAP = { 条目: 8, 动作: 100, 主题: 100, 标签: 8 };

export default function CommandPalette({ open, onClose, ctx, commands }) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef(null);

  // 全部命令（构建一次；内容搜索的 items 由 ctx 提供）。
  // 传入 commands 时直接用（ShellC 作用域命令集，ADR 0064），否则用 buildCommands(ctx)。
  const allCommands = useMemo(
    () => (commands ? commands : (ctx ? buildCommands(ctx) : [])),
    [ctx, commands]
  );

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
      style={{ backgroundColor: "rgba(20, 14, 8, 0.5)", paddingTop: "16vh" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      {/* 索书卡式检索浮层（ADR 0066）：纸卡 + serif 标题 + hairline + mono 提示 */}
      <div className="w-full max-w-xl overflow-hidden"
        style={{
          backgroundColor: "var(--card-bg)",
          border: "1px solid var(--panel-border)",
          borderRadius: "var(--radius-lg)",
          boxShadow: "var(--shadow-float), inset 0 0 46px color-mix(in srgb, var(--accent) 4%, transparent)",
          animation: "var(--motion-open)",
          animationName: "cp-enter",
        }}>
        {/* 卡头：馆藏检索 */}
        <div className="px-5 pt-4 pb-3 border-b" style={{ borderColor: "var(--panel-border)" }}>
          <div className="flex items-baseline gap-3">
            <span className="tsm-heading" style={{ color: "var(--text)", fontSize: 16, fontWeight: 600, letterSpacing: "0.04em" }}>
              馆藏检索
            </span>
            <span className="text-[10px] tracking-[0.14em]" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
              LIBRARY INDEX
            </span>
          </div>
          <div className="flex items-center gap-2 mt-3">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.5"
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
        </div>

        {/* 结果列表（独立滚动，不引入页面滚动，ADR 0028/0031） */}
        <div className="max-h-[46vh] overflow-y-auto px-3 py-2" onMouseDown={(e) => e.stopPropagation()}>
          {flat.length === 0 ? (
            <div className="px-3 py-8 text-center text-sm" style={{ color: "var(--text-secondary)" }}>
              {query.trim() ? "没有匹配的命令或资料。" : "输入内容搜索或命令…"}
            </div>
          ) : (
            groups.map(({ group, items }) => (
              <div key={group} className="mb-1.5">
                <div className="px-2 py-1 text-[10px] tracking-[0.14em]"
                  style={{ color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
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
                      className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded text-left text-[13px]"
                      style={{
                        color: "var(--text)",
                        backgroundColor: active ? "var(--surface-2)" : "transparent",
                        boxShadow: active ? "var(--focus-ring)" : "none",
                        borderRadius: 4,
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
