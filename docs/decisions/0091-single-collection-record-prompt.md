# 0091 · Phase 10-1-A-2：单条收藏后的记录引导（补齐审计首选 P1-1）

日期：2026-08-12
状态：已接受
基准：`docs/audits/10-1-A-0-experience-loop.md`（P1-1 首选范围）、10-1-A-1（空态引导）、
10-1-A-4（导入后引导 `.settings-action` 分寸）

## 一、决策

补齐 Experience Loop 首选 P1-1：Ask 检索台**单条**收藏外部结果后，toast 附加 quiet 引导
「去记录第一条回忆」→ 点击打开该作品详情并**自动聚焦「我的记忆」composer 输入框**（降低
审计反复强调的"发现成本高"）。与 10-1-A-4（导入后引导）复用同一套 `.settings-action` 分寸
（quiet，非 accent-filled）；与 10-1-A-1 同属首个记录引导语言。Bangumi 批量导入与单条收藏
是两个入口，各自独立引导。

## 二、做法

- **toast 系统扩展 action**（toast.js + ToastHost.jsx + `.toast-action` CSS）：`toast.success(msg,
  duration, action)`，ToastHost 渲染 quiet mono accent 按钮（transparent + hairline +
  radius-control，非 CTA），点击执行 `action.onClick()` 并 `dismissToast(id)` 立即消失。
- **ItemDetailPanel**：新增 `composerFocusTick` prop + composer textarea callback ref——
  挂载即聚焦（含详情异步加载后）与 tick 递增聚焦。
- **DesktopView**：
  - `handleSave`（Ask 检索台外部结果收藏）：`toast.success(..., 5200, { label: "去记录第一条回忆",
    onClick: () => { setDetailView({itemId, saved: true}); setComposerFocusTick(k+1); } })`；
  - 详情弹层内「收藏入库」同样附引导（点击即聚焦已打开的 composer）；
  - `composerFocusTick` 传入详情弹层 ItemDetailPanel。
- **存档**：`docs/audits/10-1-A-0-experience-loop.md`（完整审计原文存档，避免再丢失）。

## 三、验证

- vitest **296 passed**（292 + 4：toast action 渲染/点击消失/无 action 回归；ItemDetailPanel
  composerFocusTick 聚焦；DesktopView 集成——Ask 收藏外部结果→toast 引导→点击→composer 聚焦
  全链路）。
- 真实浏览器（真实库，真实 Ask 检索台）：收藏「命运石之门」→ toast「去记录第一条回忆」
  出现 → 点击 → 详情弹层打开且 composer textarea 获得焦点；hOverflow=false。
  截图 `mem101a2_1440.png`。
