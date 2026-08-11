# 0067 · Phase 2-0：ShellC 视觉语言统一到「馆内导览」

日期：2026-08-11
状态：已接受
基准：ADR 0066（夜书房 Shell Design System）+ Phase 1 视觉验收（次要问题 2：Classic /
ShellC 双重设计语言）

## 一、范围

只解决一个问题：ShellC（C 非对称档案室）rail 仍使用 sans 房间标签，与 Classic「馆内
导览」（serif 馆室 + mono 编号）不是同一套视觉。本小步把 ShellC rail 统一到 Phase 1
确定的 Design System。

**不改变**：ShellC 功能、房间数量、内部 section key、状态管理、数据/API、房间布局概念
（非对称房间格局不动）。

## 二、变更

- `frontend/src/index.css`：
  - `.shell-c-rail`：宽 148→176px（与 Classic rail 一致）、`--surface-1`→`--rail-bg`、
    padding/gap 对齐（16px 10px / 4px）；
  - `.shell-c-nav`：`align-items: baseline`→`center`、去 1px 边框、`transition: none`→
    motion token（`--dur-enter` + `--ease-standard`），hover `--text`、active
    accent + accent-soft（与 Classic 相同层级）；
  - `.shell-c-no`（mono 编号）：10px→9px、16px 居中、`--ink-2`（active 时 accent）；
  - 新增 `.shell-c-label`：serif（`--font-heading`）12px、letter-spacing 0.06em、weight 500
    （active 600）。
- `frontend/src/components/AppShells.jsx`：标签 span 加 `className="shell-c-label"`。

## 三、验证

- vitest **247 passed**（+1：ShellC rail 含 mono 编号 + serif 标签 + 默认激活态）。build 通过。
- 真实浏览器（Electron 离屏渲染）验证：railWidth 176、railBg `--rail-bg`、标签
  Georgia/Songti 12px/0.06em、编号 mono 9px、激活态 accent `rgb(176,90,54)` +
  accent-soft `rgb(248,244,242)`——与 Classic 一致。
