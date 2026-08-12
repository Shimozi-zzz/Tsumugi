# 0081 · Bookshelf-2.7：共享架「轻量索引」最小修正

日期：2026-08-12
状态：已接受
基准：Bookshelf-2.6 审计（共享架 954px / 73% 空 / 390 横滚 892px）、ADR 0079/0080

## 一、决策

按 Bookshelf-2.6 审计推荐（方案 C）对「零散藏书」共享架做最小视觉修正：
**标签不再逐组撑宽，书决定架宽**。数据逻辑（groupBookshelf / subgroup DOM /
每本书 button）与其它 6 个大架零变化；bookshelf.js 零改动。

## 二、做法

- **标签带移出 shelf-case**：9 个小组的 mono 索引（`RAG · 2` 等）从"subgroup 内并排的
  侧标签"改为共享架顶部一行**可换行的极轻索引带**（`.shelf-shared-index`，
  `flex-wrap: wrap`，9.5px mono / ink-2，不 badge / 不 pill / 无背景块）。
- **subgroup 只包裹书**：`.shelf-subgroup` 保留（data-testid="shelf-group"，数据语义/
  Tab 顺序/每本书 button 不变），内部不再含 label。
- **书决定架宽**：`.shelf-case` 宽度由书行决定（fit-content 已成立），标签带不再贡献
  max-content → 共享架从 954px 收敛到约 345px（≈ 剧场版 344px 同宽级）。

## 三、实测（真实库 63 册，Electron 离屏）

| 指标 | Bookshelf-2.5 | Bookshelf-2.7 |
|---|---:|---:|
| shared case width (1440) | 954px | **345px** |
| empty ratio | 73% | **26%**（普通架 20–34% 区间）|
| 1440 内部横滚 | 302px | **0** |
| 390 内部横滚 | 892px | **31px** |
| 390 empty ratio | – | 12% |
| labels inside case | 9 | **0** |
| subgroup / 标签数量 | 9 / 9 | 9 / 9（保留）|

大架 caseWidths 不变：[TV 635, 剧场版 344, 空之境界 194, 原创 189, 热血 134, 战斗 151]。
交互（点击/select/context/hover/CoverAmbient）、书姿态（bookPose）、色彩
（spineColorVaried）全保留。

## 四、验证

- vitest **274 passed**（273 + 1：共享架标签移出 shelf-case / subgroup 只包裹书）；
  build 通过。
- 真实浏览器（后端 8001 + vite 5173）：1920/1440/1024/768/390 全 `hOverflow=false`；
  共享架 5 视口宽 345/345/345/345/304、空 26%/26%/26%/26%/12%、内滚
  0/0/0/0/31px；hover/点击进「作品档案」/context menu/selectMode 63 标记+aria-pressed/
  网格 63 卡/列表 3 组 全正常；无 JS 错误。截图
  `bookshelf27_1920/1440/1024/768/390.png`。
