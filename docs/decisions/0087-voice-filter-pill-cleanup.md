# 0087 · Phase 9-1-A：Voice 过滤搜索遗漏 pill 收敛

日期：2026-08-12
状态：已接受
基准：Phase 9-0 全局审计（VoiceGraphView 过滤搜索结果仍为 accent-soft rounded-full pill，
8-2-B 因缩进差异 replaceAll 漏改）

## 一、决策

把 Voice 过滤搜索结果的 actor 条目从 accent-soft `rounded-full` pill 收敛为 `.voice-actor-link`
（与 8-2-B 已转换的快捷入口语言一致）。仅 1 处 JSX className 改动，无新 CSS。

## 二、验证

- vitest **283 passed**；build 通过；VoiceGraphView 内 `rounded-full` = **0**。
- 真实浏览器（真实库，过滤搜索态）：1920/1440/1024/768/390 全 `hOverflow=false`；
  过滤结果 actor link radius **8px**（radius-control）、非 pill、whiteOnAccent=0；
  8-2-A 回归：ego 图 interactive=focusable（语义保持）。截图 `voice91a_1920/1440/1024/768/390.png`。
