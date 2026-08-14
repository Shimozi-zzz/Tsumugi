# 0086 · Phase 8-3-A：Settings 控件语言收敛

日期：2026-08-12
状态：已接受
基准：Phase 8-3-0 审计（24 处白字实心 accent、rounded-2xl 分段 tab、rounded-xl 选择项）、
Phase 8-1-B/8-2-B（quiet control 语言）

## 一、决策

把 Settings 控件从 SaaS（白字实心 accent / rounded-xl / rounded-2xl 分段 tab）收敛为
quiet control / quiet option / quiet action。Settings 工具页语义保留（selected state /
操作层级通过 accent-soft + accent 文字 + accent 边框表达）。数据/表单/保存逻辑全冻结。

## 二、做法

- **分段 tab**（DesktopView）：`rounded-2xl` 容器 + `rounded-xl` active 白字实心 →
  `.settings-tabs`（hairline + radius-control）+ `.settings-tab` / `.settings-tab-active`
  （transparent + accent-soft/accent + accent 边框）。
- **选择项**（style theme / theme / density / ProviderSettings preset）：active 白字实心 →
  `.settings-option` / `.settings-option-active`。
- **操作按钮**（保存配置/测试/保存凭证/连接/导入/新建数据源/创建/代理保存/编辑文字涂鸦/
  插件确认/导出/导入/保存设置）：白字实心 accent（保存设置=rounded-full+shadow+scale）→
  `.settings-action`（transparent + hairline + radius-control + accent 文字；hover
  surface-2；disabled 保持）；保存设置保留 fixed 定位。
- 全部按钮补 `type="button"`；导航栏行 rounded-xl→rounded-lg（=radius-control 值）。
- **保留**：desk-askbar 卡（跨页共享，不动）、状态 pill（固定/ok 点/状态/tag）、
  进度条、toast（semantic 例外）。

## 三、验证

- vitest **283 passed**（282 + 1：管理室分段 tab/选择项/操作按钮结构断言——无 inline
  白字实心 accent、active 用 settings-tab-active）；build 通过。
- 真实浏览器（真实库）：**whiteOnAccent = 0（7 个 tab 全为 0，原 24）**；active tab =
  accent-soft + accent 文字 + accent 边框（radius 8px）；保存设置按钮 = transparent +
  accent + 8px（无 shadow/rounded-full）；新建数据源 = quiet control 且表单正常展开；
  5 视口 `hOverflow=false`；tab 切换功能正常。截图 `settings83a_1920/1440/1024/768/390.png`。
