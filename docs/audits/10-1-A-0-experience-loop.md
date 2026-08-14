# 10-1-A-0 · Experience Loop 只读审计报告（存档）

日期：2026-08-12
类型：只读审计（零代码修改）
基准：Phase 10-0 Product Value Audit → 推荐 P1「收藏→回顾闭环」

> 本文件为 Phase 10-1-A-0 审计完整原文存档。后续批次 10-1-A-1/A-2/A-3/A-4 均以本审计的
> 断点与首选范围为准执行。

## 1. Audit Result
**PASS WITH NOTES** — 记录基础设施已齐（Work Detail 内联 composer / 里程碑 / 相遇纪事 /
MemoryTimeline / 往年今日），无 P0；存在 2 处 P1 断点（获取后无记录引导、浏览面无
"已记录/未记录"信号）。

## 2. User Journey Map
```
导入(Bangumi 批量/收藏入库) → 收藏 → 浏览(Library/Bookshelf) → 打开 Work Detail → 记录(我的记忆 composer) → 回顾(时间轴/往年今日/年度总结/Ask)
         ↑ 断点A：导入/收藏完成 = 终点，无下一步引导
                                        ↑ 正常：composer 就在详情内，成本低
                                        ↑ 断点B：浏览面无"哪些还没记录"信号
```

## 3. Module Findings
| 模块 | 当前行为 | 问题 | 机会 |
|---|---|---|---|
| 收藏入库（Ask 外部详情）| toast「已收藏」→ 切已收藏模式 | 无"写一句此刻的感想"引导 | toast 附加记录入口 / 自动聚焦 composer |
| Bangumi 批量导入 | 进度 + toast「导入完成」| 完成后无下一步建议 | 摘要引导「去记录第一部」|
| Library Grid 卡片 | 有「书评」操作；`─ 记录 N 条` = **chunk 数（非经历）** | **无"已记录/未记录"经历信号** | 极轻 mono 记忆密度标记（§ N 条）|
| Bookshelf 书脊 | 无任何记录提示 | 同上 | 书脊微标记（克制）|
| Work Detail 我与它 | 状态/喜欢/评分/书评入口 | 无 | — |
| Work Detail 我的记忆 | **内联 composer 已在**：textarea + 情绪 + 附图 + 记录这一刻 + ✓完成了/↺重新打开 + MemoryTimeline | 零记忆作品无引导文案 | 空态一行 quiet 引导（降低首记成本）|
| 相遇纪事 | 自动生成状态/评分事件 | 无 | — |
| Timeline / 年度总结 | 回顾记忆 ✓ | 无 | 可反向激励（年度"这一年记了 N 条"）|
| Ask（mySearch）| 检索 works/reviews/memories ✓ | 无 | 不修改 RAG（本阶段）|

## 4. First Memory Entry Analysis
用户产生第一条记录的**现有最顺路径**：打开任一作品 → 滚动到「我的记忆」→ textarea 写一句
→ 「记录这一刻」。
- **成本低**（2 步、情绪/附图可选、里程碑一键）✓
- **发现成本高**：composer 在详情深处；首次打开作品时无任何提示告诉用户"这里可以留下你的
  感想"；收藏/导入成功后也没有把用户引到这里
- 结论：**"能记"已解决，"被引导去记"缺失**

## 5. Existing Assets（可复用）
- `mc-*` composer（ItemDetailPanel 我的记忆）——现成低成本记录组件
- `MemoryTimeline` / `相遇纪事` / `MemoryReviewModal`——记录展示
- toast 系统（收藏/导入成功均走 toast）
- HomeShrine 猫娘台词 + 往年今日——可承载"这部作品还没记录"的安静提醒
- Work Detail `onOpenReview` → Review Studio（正式书评）

## 6. Bottlenecks
- **P0**：None
- **P1**：
  1. 收藏/导入成功后无引导进入第一条记录（断点，路径终点化）
  2. 浏览面（Grid/Bookshelf）无"已记录 vs 未记录"信号（空状态缺失，用户不知从哪开始写）
- **P2**：
  3. Work Detail 零记忆/零书评作品无空态引导文案
  4. 年度总结未反向激励"今年记了几条"
- **P3**：导入摘要无下一步建议文案等细节

## 7. Recommended Next Step
**Phase 10-1-A「第一条记录引导」**（纯前端体验小步，数据/API/prompt 全冻结）：
- **首选范围（最小）**：
  1. Work Detail 零记录空态引导——该作品 memories+reviews 均为空时，「我的记忆」composer
     上方一行 quiet 引导（复用 mc-* 语言），把"这里可以留下此刻"显性化（P1-2/3）
  2. 收藏成功 toast 附加「写一句此刻的感想」入口 → 打开该作品并聚焦 composer（P1-1）
- **次选扩展**：Bangumi 导入完成摘要引导「去记录第一部」；Grid/Bookshelf 极轻 mono 经历
  密度标记（P1-2，涉及卡片+书架，surface 更大）

## 8. 批次执行状态
- 10-1-A-1：Work Detail 零记录空态引导 ✓（ADR 0088，commit 551fd91）
- **10-1-A-2：单条收藏后 toast 引导 + 聚焦 composer（本批次补齐，P1-1）** ← 本文件存档后执行
- 10-1-A-3：浏览面 § 经历密度标记 ✓（ADR 0089，commit 1bcc217）
- 10-1-A-4：Bangumi 导入后「去记录第一条回忆」✓（ADR 0090，commit fdf8760）
