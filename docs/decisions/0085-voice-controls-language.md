# 0085 · Phase 8-2-B：Voice Search & Controls 视觉语言收敛

日期：2026-08-12
状态：已接受
基准：Phase 8-2-0 审计（search pill 999px / actor pill ×9 / 白字实心 accent ×3 / threshold）、
Phase 8-1-A/B（quiet control / quiet link 语言）

## 一、决策

把 Voice Search / Controls 从旧 SaaS / pill / accent-filled 收敛为项目已验收的 quiet
control / quiet link 语言。Voice 专属局部类（不跨页复用 `.character-*`）。

## 二、做法（VoiceGraphView.jsx + index.css）

1. **Search**：`rounded-full`(999px) → `.voice-search-control`（`--radius-control` 8px）；
   背景/边框/高度/宽度/icon/placeholder/行为全不变。
2. **actor 快捷入口**（8 个，两处同构）：accent-soft `rounded-full` pill →
   `.voice-actor-link`（mono 11px accent 文字 + radius-control + hover accent-soft，
   参照 8-1-A char-detail-actor）；点击行为不变。
3. **ego「收起 / 搜索其它声优」**：白字实心 accent → `.voice-graph-action`
   （transparent + hairline + radius-control；hover surface-2）。
4. **概览切换**：active 白字实心 / inactive accent-soft → `.voice-mode-control` +
   active 修饰（accent-soft 底 + accent 文字 + accent 边框，非白字实心）。
5. **threshold 阈值按钮**：active 白字实心 → `.voice-threshold` + active 修饰。
6. 全部按钮补 `type="button"`；focus-visible = accent outline。
**冻结**：graph container rounded-2xl、overview 警示框、中心声优实心 accent 圆、Graph
节点结构 / 8-2-A 键盘语义——全不动。

## 三、验证

- vitest **282 passed**（281 + 1：search/actor/mode/threshold 结构断言——非 pill、无
  inline 实心 accent）；build 通过。
- 真实浏览器（真实库）：1920/1440/1024/768/390 全 `hOverflow=false`；search radius
  **8px**、actor link radius **8px**（非 pill）、whiteOnAccent **0**、mode 按钮 8px；
  overview active = accent-soft+accent（非白字实心）、threshold active 非白字；
  **8-2-A 回归：ego interactive=64 / focusable=64 不变**；功能（搜索/进入 ego/概览切换）
  正常。截图 `voice82b_1920/1440/1024/768/390.png`。
