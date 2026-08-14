// 人物档案馆 · 档案索引墙（Phase 8-1-A，ADR 0082）
// 从"SaaS 大圆角人物卡片墙 + pill/chip-card"收敛为"私人人物档案馆·档案索引条目"：
//  - serif 人名 + mono 编目（№ 序号）+ quiet catalog metadata（来源 · 部数 · 声优）
//  - portrait 作为档案小像（radius-cover），不是卡片主视觉
//  - 外层 radius-card / hairline / surface-1；无 pill、无 chip-card、无实心 accent、无渐变
//  - selected = accent hairline + accent-soft；hover = surface-2
// 数据/行为冻结：fetchCharacters / onOpenWork / onOpenVoice / 选中态 全保留。
import React, { useEffect, useState } from "react";
import { fetchCharacters } from "../api.js";

export default function CharacterWall({ refreshKey, onOpenWork, onOpenVoice }) {
  const [chars, setChars] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null); // 选中的角色（显示其作品）

  useEffect(() => {
    setLoading(true);
    fetchCharacters()
      .then(setChars)
      .catch(() => setChars([]))
      .finally(() => setLoading(false));
  }, [refreshKey]);

  if (loading) {
    return <div className="text-sm" style={{ color: "var(--text-secondary)" }}>加载中…</div>;
  }
  if (chars.length === 0) {
    return (
      <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
        还没有角色数据。去「问答」里搜索并收藏一部作品（如 Bangumi/萌娘百科），
        角色会在这里汇总展示。
      </div>
    );
  }

  const portraitOf = (c, cls) =>
    c.image_url ? (
      <img src={c.image_url} alt="" loading="lazy" className={cls}
        onError={(e) => { e.target.style.display = "none"; }} />
    ) : (
      <div className={cls + " flex items-center justify-center"}
        style={{ background: "var(--card-thumb)", color: "var(--accent)", fontSize: 18 }}>
        {(c.name || "?").charAt(0)}
      </div>
    );

  return (
    <div className="char-archive">
      {/* 选中角色详情（档案卡，非 SaaS 面板） */}
      {selected && (
        <div className="char-detail">
          <div className="flex items-center gap-3">
            {portraitOf(selected, "char-detail-portrait shrink-0")}
            <div className="min-w-0 flex-1">
              <div className="char-detail-name">{selected.name}</div>
              <div className="char-detail-meta">
                {selected.relation ? `${selected.relation} · ` : ""}{selected.source}
                {selected.actors && selected.actors.length > 0 ? ` · 声优：${selected.actors.join("、")}` : ""}
              </div>
              {selected.summary && (
                <div className="text-xs mt-1 line-clamp-2" style={{ color: "var(--text-secondary)" }}>{selected.summary}</div>
              )}
            </div>
            <button type="button" onClick={() => setSelected(null)}
              className="char-close shrink-0">收起</button>
          </div>
          {/* ADR 0032：声优 → 一键跳转声优关系图谱（去 pill：安静 mono 链接） */}
          {selected.actors && selected.actors.length > 0 && (
            <>
              <div className="char-detail-label">声优（点名字看关系图谱）</div>
              <div className="flex flex-wrap gap-1">
                {selected.actors.map((a) => (
                  <button type="button" key={a} onClick={() => onOpenVoice?.(a)} className="char-detail-actor">
                    {a}
                  </button>
                ))}
              </div>
            </>
          )}
          <div className="char-detail-label">出自作品</div>
          <div className="char-detail-works">
            {selected.works.map((w) => (
              <button type="button" key={w.item_id} onClick={() => onOpenWork(w)} className="char-detail-work">
                {w.image_url && (
                  <img src={w.image_url} alt="" className="char-detail-work-cover"
                    onError={(e) => { e.target.style.display = "none"; }} />
                )}
                <span className="truncate">{w.title}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 档案索引行：mono CHARACTER INDEX + 册数 + hairline */}
      <div className="char-index">
        <span className="char-index-label">CHARACTER INDEX</span>
        <span className="char-index-count">{chars.length} 位</span>
        <span className="char-index-rule" aria-hidden />
      </div>

      {/* 档案索引条目（radius-card / mono 编目 / serif 人名 / quiet meta） */}
      <div className="char-grid">
        {chars.map((c, i) => {
          const active = selected && (c.id ?? c.name) === (selected.id ?? selected.name) && c.source === selected.source;
          return (
            <button type="button" key={`${c.source}-${c.id ?? c.name}`} onClick={() => setSelected(c)}
              className={"char-entry" + (active ? " char-entry-active" : "")}>
              <span className="char-entry-no">№ {String(i + 1).padStart(3, "0")}</span>
              {portraitOf(c, "char-entry-portrait")}
              <span className="char-entry-body">
                <span className="char-entry-name">{c.name}</span>
                <span className="char-entry-meta">
                  {c.source}{c.works.length > 1 ? ` · ${c.works.length} 部` : ""}
                </span>
                <span className="char-entry-cv">
                  {c.actors && c.actors.length ? `声优：${c.actors.join("、")}` : "声优：—"}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
