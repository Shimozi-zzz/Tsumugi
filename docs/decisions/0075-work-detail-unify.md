# 0075 · Phase 3-1：统一 Work Detail 内容系统（ItemDetailPanel 为唯一基底）

日期：2026-08-11
状态：已接受
基准：ADR 0074（Work Detail 阶段约束）+ Phase 3-0 审计（ItemDetailPanel/ItemDetailModal 重复、
Classic/ShellC 分叉、三入口两套观感）

## 一、架构决策

- **ItemDetailPanel 成为唯一 Work Detail 内容基底**（保留全部既有能力：外部世界 +
  我的记录 + composer + 里程碑 + MemoryTimeline + Ambient）。
- **ItemDetailModal 不再作为第二套详情 UI**：Classic 原 `openItemDetail` 打开的只读弹层
  迁移到统一容器（浮层 + ItemDetailPanel）；ItemDetailModal 文件保留（其单元测试仍在），
  待确认无职责后再决定删除。
- **统一的是内容系统，不强制外层容器一致**：Desktop master-detail 右栏、Mobile 全屏
  Detail Scene、ShellC 作品档案浮层各自保留容器形式，内部都渲染同一 ItemDetailPanel。

## 二、ItemDetailPanel 新增（最小 props，职责清晰）

- `externalDetail`：外部未收藏详情（无 itemId），只呈现作品本身 + 这个世界 + 外部操作，
  无我的记录/composer/时间轴；
- `refreshKey`：「刷新资料」后重取详情；
- `onSaveDetail / onShareDetail / onRefreshDetail`：收藏入库/安利卡/刷新的回调（由调用方
  传入，Panel 不承担新后端业务、不复制请求逻辑）。
- 外部操作区位于「外部世界」结束处（未来「我与它」之前）。

## 三、入口迁移（均指向统一容器/面板）

- `openItemDetail`（网格/书架/HomeShrine/CharacterWall/右键查看详情）→ `setDetailView({itemId, saved:true})`，浮层渲染 ItemDetailPanel；
- `openExternalDetail`（检索台外部命中）→ `setDetailView({externalDetail, saved:false})`；
- `detailSave`（收藏入库）→ 保存成功后 `setDetailView({itemId: res.item_id, saved:true})` 切换为已收藏模式；
- `handleRefreshExternal` → 刷新 + `detailRefreshKey` 重取；
- MemoryGallery / VoiceGraphView / 列表视图 / 移动 Detail Scene → 原有 `detailBrowseId` → ItemDetailPanel（已统一）。

## 四、保持不变

- 未改后端/API/数据模型/Collection 语义/Memory/Review；
- 未做 3-2 叙事重组；未改 InfoTable/角色展示/MemoryTimeline/composer/ReviewStudio/
  MemoryReviewModal/MemoryTypeTag/Library/Gallery/Timeline。

## 五、验证

- vitest **250 passed**（+2：外部未收藏模式=收藏入库+外部世界且无我的记录；已收藏模式=
  安利卡/刷新+我的记录）。build 通过。
- 真实浏览器：Classic 已收藏详情=统一容器+我的记录+安利卡/刷新（无收藏入库）；
  ShellC 作品档案=同一面板；Mobile 详情打开无横向溢出。外部未收藏场景由组件测试覆盖
  （真实联邦检索依赖网络/Connector，未实跑）。
- ItemDetailModal：无 App 运行时引用（仅 characters.test 单元测试），具备删除条件但
  本阶段不删（需先迁移该测试）。
