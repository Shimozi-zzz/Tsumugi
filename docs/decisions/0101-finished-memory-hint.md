# 0101 · Phase 10-1-C-2：「看完」记录时机就近提示

日期：2026-08-12
状态：已接受
基准：C-2 Audit（缺口：标记「看完」= 最自然的记录时机，但状态行无就近提醒）、C-1（composer 价值提示）

## 一、决策

Work Detail「我与它」当前状态行下，**仅当 `colStatus === "看完"`** 时显示一行 quiet inline
hint，提醒这是记录此刻的自然时机。不新增按钮/CTA/弹层/toast；不改 composer 交互、控件
顺序或任何既有逻辑；复用现有 `.wd-hint`（mono 11px ink-2）——**零 CSS 新增**。

## 二、实现（frontend/src/components/ItemDetailPanel.jsx）

```
{colStatus === "看完" && (
  <p className="wd-hint" style={{ marginTop: "var(--sp-2)" }}>
    刚看完的话，写一句此刻的感想——它会进入时间轴，成为 Ask 回想这一刻的线索。
  </p>
)}
```
位置：当前状态行下方（就近）；文案聚焦"刚看完/此刻"，用「时间轴/线索/回想」，不重复
C-1 的情绪·里程碑解释，不承诺 Ask 一定回答。

## 三、验证

- vitest **299 passed**（297 + 2：状态=看完 → hint 含 时间轴/Ask/线索 且 composer + C-1 价值
  提示保持；状态≠看完 → 无 hint）；build 通过。
- 后端 pytest **483 passed**（未动）。
- 真实浏览器（真实库，5 视口 1920/1440/1024/768/390）：切换状态 默认→无 hint、「看完」→
  hint 出现、「在看」→ hint 消失；composer + 价值提示保持；全 `hOverflow=false`。截图
  `val101c2_1440.png`。
- git diff 仅 `ItemDetailPanel.jsx` + `characters.test.jsx`；无 CSS 变更；backend/API/schema/
  retrieval/Prompt/Ask UI/Library/Bookshelf/Bangumi 未动；未创建 Memory；memory id=61 未删。
