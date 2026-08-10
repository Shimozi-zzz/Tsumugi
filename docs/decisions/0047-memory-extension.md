# 0047 · Memory 扩展：轻量文字 / 里程碑 / 情绪 / 媒体附件（P3）

日期：2026-08-10
状态：已接受
基准：prompts/07_WORK_MODEL_AUDIT（Personal 轴）+ 14_DATABASE_ARCHITECTURE（Media 实体 / Memory 字段）+ PROJECT_AUDIT P3

## 一、范围

Memory 从"只能由书评生成"扩展为可**直接创建**：轻量文字（一句话感想）、里程碑（完成/
重新打开），可选**情绪**标记与**媒体附件**（截图/插图）。

**本轮不做**：收藏动作之外的自动采集（收藏时刻已在 P2 做）、视频/音频附件、Memory 编辑
（创建后可删不可改）、按情绪聚合视图。

## 二、核心决策

1. **直接创建（不经过书评）**：`POST /items/{id}/memories`（multipart：summary/source_type/
   emotion/file）；`source_type ∈ {text, milestone}`；summary 即正文；`occurred_at=现在`；
   `source_ref=NULL`（无主记录，多态引用本就允许）。
2. **emotion 可选列**：`memories.emotion`（VARCHAR，固定小集 开心/感动/遗憾/怀念/平静/治愈，
   前端 chips/下拉；后端不强制枚举——留自由）。展示为时间轴/回廊/弹层上的小标签。
3. **Media 附件实体**：`media` 表（id/item_id/memory_id/file_path/media_type/size）；文件存
   `data/uploads`，`/static/uploads` 服务；`Memory.media` 关系 `cascade="all, delete-orphan"`；
   一条记忆可带多张（时间轴缩略图最多展示 3 张，弹层全展示）。
4. **删除**：`DELETE /memories/{id}` 仅允许 text/milestone（含媒体级联删除）；review/collection
   记忆由各自系统管理，不允许误删。
5. **只删不改**：直接记忆创建后不可编辑（保持记录的时间真实性），可删除重记。

## 三、与既有决策的关系

- 对 ADR 0041（Memory 独立容器、source_type 预留 text/collection/milestone）：本轮正式启用
  text 与 milestone 两个来源类型；
- 对 ADR 0046（收藏时刻 Collection Memory）：collection 类型记忆保持"自动生成"语义，不参与
  手动创建/删除；
- 对 ADR 0042/0044（时间轴/往年今日）：时间轴展示新增 类型徽标/情绪/媒体缩略图；往年今日
  只对 review 类型记忆触发（保持其"唤起书评"语义）。

## 四、接口

- `POST /items/{id}/memories`（multipart：summary/source_type/emotion/file）
- `DELETE /memories/{id}`（text/milestone）
- `MemoryOut` 增 `emotion` 与 `media: [{id, url, media_type}]`（url 由 file_path 转 /static）

## 五、测试与实测

- pytest **433 passed**（+7 `test_memories.py` 新组 + `test_memories`：text/milestone 创建、
  非法 source_type/空/不存在 item、delete 仅 direct、API 创建含 emotion+media 落库、校验与
  删除、列表含 emotion），覆盖率 87.47%。
- vitest **207 passed**（+1：text 记忆类型徽标/情绪/媒体缩略图/点击弹层/删除）。
- 实测见简报（真实作品创建一条带情绪的轻量记录，时间轴展示类型徽标+情绪+媒体缩略图，
  截图）。
