# 0100 · Phase 10-1-C-1：Memory Value Signaling

日期：2026-08-12
状态：已接受
基准：Phase 10-1-C-0 审计（P2-B：用户"知道可记录但不知道为何记录 / 为何选情绪·里程碑"）
决策 B（MICRO EXPERIENCE）

## 一、决策

Work Detail「我的记忆」composer 增加极轻价值说明（非 CTA），让用户理解记录会进入时间轴、
情绪/里程碑会成为以后 Ask 回想个人经历的线索。仅前端体验：ItemDetailPanel.jsx + index.css +
对应测试。不改变创建/保存/情绪/附图/里程碑/完成·重新打开逻辑；不改数据模型/API/retrieval/
Prompt/Ask UI。

## 二、UX 变化

- **composer 价值提示**（`.mc-value-hint`，置于情绪/附图行与「记录这一刻」之间，极轻 mono
  10px ink-2，无背景/边框/阴影）：文案
  「情绪和里程碑，会帮助时间轴与 Ask 回想这是怎样的一刻。」
- **零记录空态文案**（`.mc-empty-hint` 仅改文案）：
  「这部作品还没有你的记录——写一句此刻的感想即可，之后它会出现在时间轴与往年今日里，
  也会成为 Ask 回想你与它经历的线索。」（用「线索」「回想」等符合实际 retrieval 行为的
  措辞，不虚构/不承诺 Ask 一定回答。）

## 三、验证

- vitest **297 passed**（296 + 1：C-1 价值提示存在 + 控件全保留；零记录空态文案断言含
  时间轴/Ask/回想线索）；build 通过。
- 后端 pytest **483 passed**（本阶段未动后端，状态一致）。
- 真实浏览器（真实库，5 视口 1920/1440/1024/768/390）：`hOverflow=false` 全通过；有记录
  作品（莉可丽丝）→ value hint + composer + 情绪/附图/里程碑 全正常；零记录作品
  （魔法少女小圆 NO.0）→ 空态新文案 + value hint + composer。截图 `val101c1_1440.png`。
- git diff 仅 `ItemDetailPanel.jsx` + `index.css` + `characters.test.jsx`。
