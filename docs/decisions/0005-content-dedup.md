# 0005 · 重复内容去重（内容指纹 + force 强制导入）

日期：2026-08-05
状态：已接受（Phase 1 收尾）

## 背景

重复导入同一文档/图片会原样新建 Item + 重新切分 + 重新生成向量，造成：
- 存储与 embedding 时间浪费；
- 检索 top-k 被同一内容的重复副本稀释，降低结果多样性；
- 删除时只删当前条目，历史副本残留。

## 决策

采用**方案 A：默认静默跳过 + force 强制导入**（用户已确认）：

1. **指纹**：`Item` 新增 `content_hash`（sha256，String(64)，可空，历史数据为
   NULL 不参与判重）。
   - note：`sha256(content.encode("utf-8"))`
   - image：`sha256(文件字节)`（**按文件内容**判重，路径不同但内容相同也算
     重复；读取失败返回 None 则跳过判重）
2. **入库判重**：`ingest_text_document` / `ingest_image` 在写入前查
   `content_hash` 是否已存在；存在则直接返回已有 Item，**不重复写向量**。
   `force=True` 时跳过判重强制再导入。
3. **API**：`ItemCreate.force`（JSON）与 `upload_item` 的 `force` Form 字段；
   响应 `IngestResponse` 新增 `duplicated: bool` 标记，前端提示
   "内容已存在，跳过导入"。
   - 图片上传在判重命中时**提前返回，不再写附件文件**，避免重复文件堆积。
4. **旧库迁移**：`database.py` 新增 `ensure_schema()`——`create_all` 不会给
   已有表加列，故对存在 items 表的库执行
   `ALTER TABLE items ADD COLUMN content_hash VARCHAR(64)`；`main.py` 启动时调用。

## 权衡

- 放弃"重复时报错"：静默跳过更贴近"个人图书馆"的直觉（重复整理不报错）。
- 放弃"重复 + 合并标签"（方案 B）：增加语义复杂度，Phase 2 标签系统落地时
  可再议；现阶段重复导入通常不需要改标签。
- hash 只做**字节级精确判重**：内容差一个空格即视为不同文档，语义级去重
  不在 Phase 1 范围（成本高、误伤风险大）。

## 已知限制

- 历史数据 `content_hash` 为 NULL，去重只对新增数据生效；如需回填需脚本扫描
  content/file 重新计算（未实现）。
- 并发同文档同时导入可能出现竞态双写（SQLite 单机低概率，未做唯一约束）。
