# 0070 · Phase 2-3：Library 工具栏 / 筛选 →「整理书架」

日期：2026-08-11
状态：已接受
基准：ADR 0066/0068/0069 + Phase 2 命题（"我在整理我的藏书"，不是"操作数据库"）

## 一、三级操作层级

- **Level 1 · 搜索**：置左成为最自然入口（纸感 hairline，focus-ring，占位保留
  「查找存储的内容…」，有词显示 ✕ 清除）。
- **Level 2 · 视图切换**：紧凑安静，active 由"白字实心 accent"降为 accent-soft +
  accent 文字。
- **Level 3 · 批量选择**：默认安静（ink-2 文字、无填充）；仅进入 Selection Mode 后
  获得权重（accent + accent-soft，底部批量栏出现）。
- 排序：现有 Library 无内容排序能力，按要求不新增逻辑，未加入。

## 二、书架范围行（当前筛选一目了然）

- 常显 `共 N 册`（mono 微字，降为辅助信息，不再作为主标题 pill）；
- 作品类型筛选并入该行（全部类型 + 类型，mono 微字，active=accent+accent-soft，
  inactive=ink-2，无彩色 chips 墙）；
- 激活的其它筛选（标签 # / 分组 / 搜索词）以可清除的小标展示（✕ 各可删）+「清除筛选」；
- 移除原"全部资料 + 计数 pill"主标题（由 PageHeader + 范围行承接）。

## 三、Accent / Motion

- Normal 模式无实心 accent 元素；accent 只用于当前筛选/焦点/主操作/Selection Mode；
- 视图切换与选择使用 motion token（--dur-enter + --ease-standard），无按钮堆动画。

## 四、Responsive（本步最小兼容）

- 搜索框 `w-full sm:w-72`（390 全宽 277px）；工具栏 flex-wrap；实测 1920/1440/1024/390
  均无横向溢出。

## 五、验证

- vitest **248 passed**（搜索占位/「选择」/「全部类型」/视图 title 均保留，无回归）。
  build 通过。
- 真实浏览器（Electron 离屏）：搜索置左且为首控件；Normal 模式实心 accent 元素 0；
  范围行「共 63 册」；Selection Mode 底部批量栏出现且可见、选择按钮转 accent；
  390 搜索全宽、无横向溢出。截图 tool23_1920/1440/1024/390.png。
