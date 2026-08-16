// 共享 UI 组件（Playnite 式信息设计，ADR 0029）
// - InfoTable：label 右对齐 / value 左对齐 / 行间细分隔线的属性表格
// - TagCapsule：统一圆角胶囊标签（用主题 --tag-bg/--tag-text 微弱变色，不随机上色）
// 全部走 token，四套主题（含深色）统一生效。
import React from "react";

/** 统一标签胶囊：单一圆角矩形样式，颜色用主题 tag token（accent 系微弱变化）。 */
export function TagCapsule({ text, title, onClick, muted = false }) {
  return (
    <span
      className="px-2 py-0.5 rounded-full text-[11px] whitespace-nowrap inline-flex items-center gap-1"
      title={title}
      style={{
        backgroundColor: muted ? "transparent" : "var(--tag-bg)",
        color: muted ? "var(--text-secondary)" : "var(--tag-text)",
        border: muted ? "1px dashed var(--panel-border)" : "none",
        cursor: onClick ? "pointer" : "default",
      }}
      onClick={onClick}
    >
      {text}
    </span>
  );
}

/**
 * 属性表格：label 右对齐 / value 左对齐 / 行间细分隔线（Playnite 式信息排版）。
 * rows: [{label, value}]，value 可为 React 节点。
 */
export function InfoTable({ rows, className = "" }) {
  const visible = (rows || []).filter((r) => r.label && r.value != null && r.value !== "");
  if (visible.length === 0) return null;
  return (
    <table className={"w-full border-collapse text-[13px] " + className}>
      <tbody>
        {visible.map((r, i) => (
          <tr key={i}
            style={i === 0 ? undefined : { borderTop: "1px solid var(--panel-border)" }}>
            <td className="py-1.5 pr-4 align-top whitespace-nowrap"
              style={{ width: "30%", textAlign: "right", color: "var(--text-secondary)" }}>
              {r.label}
            </td>
            <td className="py-1.5 pl-4 align-top" style={{ textAlign: "left", color: "var(--text)" }}>
              {r.value}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * 档案编号（本轮新增）：§ + 等宽数字的编辑档案式标签，如 §01。
 * 用于"本质上是被编目的档案"的位置（记忆回廊年份、时间轴条目、书评记录等），
 * 增强"被认真编目的私人档案"的感觉。size: "sm"（默认，条目级）/ "lg"（年份大标题）。
 */
export function ArchiveNo({ children, size = "sm", color = "accent", className = "" }) {
  return (
    <span className={"archive-no archive-no-" + size + " " + className}
      data-testid="archive-no"
      style={{ color: color === "muted" ? "var(--text-secondary)" : "var(--accent)" }}>
      <span className="archive-no-mark">§</span>
      <span className="archive-no-num">{children}</span>
    </span>
  );
}

const SRC_LABEL = { bangumi: "Bangumi", moegirl: "萌娘百科", vndb: "VNDB", local: "本地" };

/**
 * 从条目详情（ItemDetailOut + raw_metadata.detail.metadata）提取"基本信息"属性行。
 * 供 InfoTable 使用：来源/原名/日期/平台/开发商/评分/投票数/卷数/集数/页面信息等。
 */
// P1 Work 模型作品类型（ADR 0045）：galgame 涵盖视觉小说
export const WORK_TYPES = ["anime", "manga", "game", "galgame", "novel", "other"];
export const WORK_TYPE_LABEL = { anime: "动画", manga: "漫画", game: "游戏", galgame: "Galgame", novel: "小说", other: "其它" };
// P2 收藏状态（ADR 0046）
export const COLLECTION_STATUSES = ["想看", "在看", "看完", "搁置", "弃坑"];
// P3 记忆情绪（ADR 0047）：固定小集 + 自由
export const MEMORY_EMOTIONS = ["开心", "感动", "遗憾", "怀念", "平静", "治愈"];
export const MEMORY_TYPE_LABEL = { review: "书评", text: "记录", milestone: "里程碑", collection: "收藏" };

/**
 * 统一页面头（ADR 0066 夜书房 Shell）：serif 房间名 + hairline + mono 路径。
 * 全站唯一标题体系，禁止各页面另起标题。
 * path 传相对路径（如 "书库 ▸ 网格"），children 为右侧附加内容（工具/操作）。
 */
export function PageHeader({ room, path, children }) {
  return (
    <header className="page-header" data-testid="page-header">
      <div className="flex items-center gap-2.5 min-h-[44px] min-w-0">
        <h1 className="page-header-room">{room}</h1>
        {path ? <div className="page-header-path">{path}</div> : null}
        {children ? <div className="page-header-extra">{children}</div> : null}
      </div>
    </header>
  );
}

/**
 * 记忆类型小标（Phase D · 情感权重呈现，ADR 0063）：回顾场景里让"收藏时刻/完成时刻"
 * 被自然识别，克制安静——书评保持正式 pill，轻量记录中性化，完成时刻暖色、收藏时刻
 * 降为入藏注记。不新增情感评分/字段/AI。
 */
export function MemoryTypeTag({ sourceType }) {
  const t = sourceType || "";
  if (t === "collection") {
    return (
      <span className="ml-1.5 inline-flex items-center rounded px-1 py-px text-[10px] tracking-wider whitespace-nowrap"
        style={{ color: "var(--text-secondary)" }}>＋ 收藏</span>
    );
  }
  if (t === "milestone") {
    return (
      <span className="ml-1.5 inline-flex items-center rounded px-1 py-px text-[10px] tracking-wider whitespace-nowrap"
        style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)", fontWeight: 600 }}>✓ 完成</span>
    );
  }
  if (t === "text") {
    return (
      <span className="ml-1.5 inline-flex items-center rounded px-1 py-px text-[10px] tracking-wider whitespace-nowrap"
        style={{ backgroundColor: "var(--panel-border)", color: "var(--text-secondary)" }}>记录</span>
    );
  }
  const label = MEMORY_TYPE_LABEL[t] || t || "";
  return (
    <span className="ml-1.5 inline-flex items-center rounded px-1 py-px text-[10px] tracking-wider whitespace-nowrap"
      style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>{label}</span>
  );
}

export function itemInfoRows(detail) {
  if (!detail) return [];
  const raw = detail.raw_metadata && typeof detail.raw_metadata === "object" ? detail.raw_metadata : null;
  const meta = raw?.detail?.metadata || {};
  const rows = [];
  if (detail.source) rows.push({ label: "数据源", value: SRC_LABEL[detail.source] || detail.source });
  if (detail.work_type) rows.push({ label: "类型", value: WORK_TYPE_LABEL[detail.work_type] || detail.work_type });
  if (detail.alternative_title || meta.original_name) rows.push({ label: "原名", value: detail.alternative_title || meta.original_name });
  const release = detail.release_date || meta.date || meta.released;
  if (release) rows.push({ label: "发行日期", value: String(release) });
  if (meta.platform) rows.push({ label: "平台", value: String(meta.platform) });
  if (Array.isArray(meta.developers) && meta.developers.length) rows.push({ label: "开发商", value: meta.developers.join("、") });
  if (detail.rating != null) rows.push({ label: "大众评分", value: `${detail.rating} / 10` });
  if (detail.my_rating != null) rows.push({ label: "我的评分", value: `${detail.my_rating} / 10` });
  if (detail.social?.votecount != null) rows.push({ label: "投票数", value: String(detail.social.votecount) });
  if (meta.volumes != null) rows.push({ label: "卷数", value: String(meta.volumes) });
  if (meta.eps != null) rows.push({ label: "集数", value: String(meta.eps) });
  if (detail.social?.rating_rank != null) rows.push({ label: "评分排名", value: `第 ${detail.social.rating_rank} 名` });
  if (detail.social?.page_info?.length != null) rows.push({ label: "页面长度", value: `${detail.social.page_info.length} 字节` });
  if (detail.social?.page_info?.touched) rows.push({ label: "最后编辑", value: String(detail.social.page_info.touched).slice(0, 10) });
  return rows;
}
