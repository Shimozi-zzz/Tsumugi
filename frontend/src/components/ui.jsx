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

const SRC_LABEL = { bangumi: "Bangumi", moegirl: "萌娘百科", vndb: "VNDB", local: "本地" };

/**
 * 从条目详情（ItemDetailOut + raw_metadata.detail.metadata）提取"基本信息"属性行。
 * 供 InfoTable 使用：来源/原名/日期/平台/开发商/评分/投票数/卷数/集数/页面信息等。
 */
export function itemInfoRows(detail) {
  if (!detail) return [];
  const raw = detail.raw_metadata && typeof detail.raw_metadata === "object" ? detail.raw_metadata : null;
  const meta = raw?.detail?.metadata || {};
  const rows = [];
  if (detail.source) rows.push({ label: "数据源", value: SRC_LABEL[detail.source] || detail.source });
  if (meta.original_name) rows.push({ label: "原名", value: meta.original_name });
  if (meta.date) rows.push({ label: "日期", value: String(meta.date) });
  if (meta.released) rows.push({ label: "发行日期", value: String(meta.released) });
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
