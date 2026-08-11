# 0063 · Memory 类型的情感权重呈现（Memory Rediscovery）

日期：2026-08-11
状态：已接受
基准：docs/product-brief-v1.1.md（记忆回廊 / 被动重逢）+ ADR 0047（source_type）+ 0062
（完成时刻 milestone 自动采集）+ AGENT_UI.md（安静、克制、编辑设计）

## 一、动机

Phase D 后 Memory 来源已有多类（review/text/milestone/collection），但回顾场景里：
- Timeline：所有类型共用同一 accent-soft 徽标，收藏/完成时刻与轻量记录**同权重**；
- 记忆回廊：行内**完全没有类型标记**，"收藏时刻/完成时刻"无法被自然识别。

目标：不新增情感评分/AI/字段，仅用**克制的视觉层级**让"收藏时刻/完成时刻"在回顾中
被自然识别，保持私人图书馆安静、沉浸的风格。

## 二、视觉层级设计

新增共享 `MemoryTypeTag`（frontend/src/components/ui.jsx），按 source_type 分级：

| 类型 | 标记 | 视觉 | 语义 |
|---|---|---|---|
| review 书评 | `书评` | accent-soft pill（保持原样） | 正式记录，默认形态 |
| text 记录 | `记录` | neutral pill（panel-border bg） | 轻量随记，中性化 |
| milestone 完成时刻 | `✓ 完成` | accent pill + 加粗（暖） | 里程碑，暖色强调 |
| collection 收藏时刻 | `＋ 收藏` | muted 无 pill | 档案入藏注记，降噪 |

时间轴圆点：收藏时刻用暖石 muted（`color-mix(accent 40%, panel-border)`），其余可点
类型保持 accent——"入藏"安静、"完成"温暖。

记忆回廊：**仅非 review 类型**显示标记（书评是默认形态，行保持干净），让特殊时刻在
全局"回廊"里被一眼认出。

## 三、明确不做

- 不做情感评分系统 / 数值权重 / AI 情感分析；
- 不新增 Memory 字段或实体；
- 不重排 Timeline/Gallery 架构（只替换徽标渲染 + 加标记 + 点色）；
- 不改变点击/删除/弹层行为。

## 四、测试与实测

- vitest：+2（Timeline milestone `✓ 完成`、collection `＋ 收藏` 且不可点击；Gallery
  收藏/完成标记渲染、书评行保持干净）；全量 235 passed。build 通过。
