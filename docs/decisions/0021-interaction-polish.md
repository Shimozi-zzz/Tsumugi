# 0021 · 交互细节打磨：批量操作 + 右键菜单 + 键盘快捷键 + Toast 反馈

日期：2026-08-06
状态：已接受

## 背景

解决"交互细节缺失"：批量选中、右键快速操作、键盘导航、明确的操作反馈，
让软件有"管理工具的分量感"。所有新增交互元素视觉上复用上一轮（ADR 0020）
定义的设计 token（--panel/--panel-border/--shadow-md/--radius-* 等），不引入
新风格。

## 一、批量选择（网格 + 书架）

### 交互方式选型（决策）
选**显式"选择"模式开关 + 点击选中**，而非长按/Ctrl+点击：

- 长按与现有"卡片点击打开详情"冲突、且不可发现；Ctrl+点击对触屏/新手不直观；
- 显式开关最符合"管理工具"心智：点"选择"进入模式，点击卡片切换选中（不打开
  详情），再次点"选择"或 Esc 退出；
- 选中视觉：accent 描边 + 左上角 ✓ 角标（复用 `--accent`，不新引入颜色）。

### 批量操作（底部操作栏："已选中 N 项 + 打标签 / 删除 / 取消"）
- **批量打标签**：弹 `TagEditModal`（标签串 + 添加/替换/移除三态）→
  `POST /items/batch/tags`；
- **批量删除**：`window.confirm` 二次确认 → `POST /items/batch/delete`；
- 批量导出：当前无导出能力，跳过（任务允许）。

### 后端
- `ingest.set_item_tags(item_id, tag_names, mode)`（add/remove/set，单条与批量
  复用）；`ingest.delete_items(item_ids)` 复用 `delete_item` 的向量/附件/孤立
  标签清理。
- 端点：`POST /items/batch/tags`、`POST /items/batch/delete`、
  `POST /items/{id}/tags`。**注意路由顺序**：`/items/batch/...` 必须在
  `/items/{item_id}/...` 之前声明，否则 "batch" 会被 `{item_id}` 捕获。

## 二、右键上下文菜单

- 条目（网格卡片 / 书架书脊）`onContextMenu` 弹出；菜单项：查看详情 / 编辑标签
  / 写读后感 / 生成安利卡 / 删除。
- 收藏/取消收藏未放：库内条目都已收藏，无"未收藏"态，避免与删除语义混淆。
- 样式复用 token（细边框 + `--shadow-md`，无磨砂/渐变）。
- 定位：`getBoundingClientRect` 测量后钳制在视口内（8px 边距）；点击外部遮罩 /
  Esc / 再次右键关闭。

## 三、键盘快捷键（核心高频，方向键跳过）

- **`/` 或 `Ctrl+K`**：聚焦问答搜索框（输入框内不劫持 `/`；Ctrl+K 始终生效）；
- **Esc**：依次关闭 右键菜单 → 标签弹层 → 快捷键说明 → 退出选择模式 → 详情 →
  安利卡 → 书评 → 导入浮层；
- **`?`**：开/关快捷键说明弹层（可发现性：导航栏底部加了 "?" 帮助按钮）；
- **方向键导航条目：跳过**——需要网格/书架各自的"焦点态 + scrollIntoView +
  与选择模式/鼠标悬停的交互协调"，复杂度与收益不成比例，记入后续（ADR 明示）。

## 四、Toast 反馈系统

- `toast.js`：模块级命令式 API（`toast.success/error/info`），`ToastHost`
  订阅渲染右下角堆叠。
- 视觉：`--panel` 底 + `--panel-border` 细边框 + `--shadow-md` + `--radius-md`，
  类型色点（success=`--ok`/error=`--danger`/info=`--accent`）；自动消失
  （成功 2.6s / 错误 4.2s），不过度堆叠、不长时间停留。
- 接入：导入成功/失败、创建笔记、收藏入库、单条删除、批量打标签/删除、
  单条标签、Provider 保存/测试连接；移除原 importMsg/connMsg/askError 的部分
  静默或内联反馈（askError 在问答区仍保留上下文提示）。

## 五、测试与实测

- **vitest +11（interactions.test.jsx）**：Toast（成功渲染/自动消失/类型区分）、
  批量（选择计数/打标签请求体/删除请求体/Esc 退出）、右键菜单（弹出/Esc 关闭/
  删除请求）、快捷键（`?` 开关、Ctrl+K 聚焦、帮助按钮）。全量 vitest 64 passed。
- pytest **271 passed**（+5 批量/单条标签与删除：add/set/remove、批量删除、
  空列表、404）。build 通过。
- **实测（真实后端 API）**：创建 3 笔记 → `POST /items/batch/tags`
  （updated:3，三条目均获 [批量,收藏]）→ 单条 set → `POST /items/batch/delete`
  （deleted:1）→ 条目列表正确减少。前端交互（批量栏/右键/`/` 聚焦/toast）由
  集成测试对真实组件验证；测试数据已清理。

## 六、Electron 实机验证（追加，CDP 驱动真实点击）+ 顺带修复一个真实 bug

用 CDP（Chrome DevTools Protocol）驱动真实 Electron 客户端（加载 vite 页 +
后端 8001）逐项实机点击，**并发现并修复了一个组件测试覆盖不到的真实 bug**：

### 顺带修复：Electron 下所有 API 请求 404
- **现象**：实机打开图书馆显示空库（全部/笔记计数均为 0），但直接 `fetch`
  `http://127.0.0.1:8001/api/items` 正常返回 17 条。
- **根因**：`frontend/electron/preload.cjs` 注入的 `apiBase` 是
  `http://127.0.0.1:8001`，而 `api.js` 统一用 `` `${API_BASE}/items` `` 拼 URL，
  Web 模式 `API_BASE="/api"` 正确，但客户端模式拼成了
  `http://127.0.0.1:8001/items`（**缺 `/api` 前缀**）→ 全部 404 →
  `fetchItems` 抛"获取条目失败" → 静默 catch → 空库。
- **修复**：`apiBase` 改为 `http://127.0.0.1:8001/api`（`filePathToUrl` 用
  `API_BASE.replace(/\/api$/, "")` 拼 `/static`，不受影响）。
- **为什么组件测试没抓到**：测试 mock 了 `fetch`，apiBase 拼 URL 的差异不会
  暴露；只有真实客户端连真实后端才会触发。

### 实机结果（12/12 全过）
- **A. 右键菜单视口钳制**：`Emulation.setDeviceMetricsOverride` 缩窄视口到
  680×560 使卡片贴近边角，在右下角卡片上右键 → 菜单 rect
  `{left:454, right:664.7, top:369.7, bottom:552}`，vw=680/vh=560 —— **完全在
  视口内，未溢出**。
- **B. 批量选择 12 项**：批量栏"已选中 12 项"、12 个 ✓ 角标、选中卡 inline
  `borderColor: var(--accent)` + accent-soft 光圈；选择 12 项耗时 31ms（无卡顿）。
- **C. Toast 堆叠**：快速批量打标签 + 3 条连续触发 → 4 个 toast 纵向堆叠且
  rect 互不重叠；3.2s 后成功类自动消失（4→2）。
- **D. 完整流程**：`/` 聚焦搜索 → 输入"辉夜测试" → Esc → `?` 打开快捷键说明
  → Esc → 右键条目 → "写读后感" → 书评面板打开。全部通过。
- 测试数据（15 条实机笔记）已清理；回归 vitest 64 / pytest 271 / build 通过。
