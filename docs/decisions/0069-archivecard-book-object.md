# 0069 · Phase 2-2：ArchiveCard →「书 / 索书卡」视觉物件

日期：2026-08-11
状态：已接受
基准：ADR 0066/0068 + Phase 2 命题（"让 ArchiveCard 像私人书架上的一本书 / 一张索书卡"）

## 一、视觉层级（封面为第一锚点）

ArchiveCard 视觉顺序改为：**Cover → Title → 编目行（NO. · 来源）→ 索书卡元数据行
（─ 编目号/来源/记录）→ 次级操作**。封面成为主要视觉锚点；Badge/状态/操作不与封面
争夺焦点。保留全部既有信息与交互（数据来源/Item 关系/类型/状态/收藏/记录数/点击/
右键/选择/hover/focus/书评/删除）。

## 二、纸与墨 / 边框 / 阴影

- 去掉原 inset 暖色内晕与浮起阴影 → 仅 `0 1px 2px rgba(43,36,26,0.05)` 轻微环境层次；
- hairline 边框、纸感 surface、近直角（Surface 6 / Cover 4），无渐变/玻璃/发光；
- Hover 安静：边框微染 accent 35% + 封面图 `scale(1.02)` + 次级操作淡入（不再上浮）；
- motion 统一用 `--dur-enter` + `--ease-standard`。

## 三、状态与标记

沿用既有 MemoryTypeTag 语言（本次 ArchiveCard 不新增徽标）；类型信息保持克制
（`archive-card-type` 中性小字）；accent 仅用于 NO. 编目号与主操作。

## 四、键盘焦点

- ArchiveCard 增加 `role="button"` + `tabIndex=0` + `onKeyDown`（Enter/Space 打开），
  支持键盘可达；`:focus-visible` 应用 `--focus-ring`（含键盘可见焦点环）。
- Selected 保持 accent 边框 + accent-soft 环。

## 五、Responsive（本步只保证自身不破坏）

三个视口（1920/1440/390）实测无横向溢出、长标题 line-clamp 2、封面 3/4 比例稳定、
封面占位（档案书脊轮廓）保留。

## 六、验证

- vitest **248 passed**（+1：封面为第一子元素 + 键盘 Enter/Space 打开）。build 通过。
- 真实浏览器（Electron 离屏）：封面 aspect 3/4、卡圆角 6px、阴影无 inset、标题
  serif + clamp 2、meta/lines 保留、Ambient 在卡外（Scene Layer）、390 无横向溢出。
- 注意：离屏渲染无法模拟真实 Tab 焦点，`:focus-visible` 焦点环请在实际浏览器 Tab
  验证（规则与键盘打开已由 CSS/vitest 覆盖）。
