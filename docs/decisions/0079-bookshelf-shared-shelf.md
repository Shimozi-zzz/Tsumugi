# 0079 · Bookshelf-2：共享架 / 色彩节奏 / 移动紧凑（P1·P2·P3）

日期：2026-08-12
状态：已接受
基准：Bookshelf-1.5 审计（ADR 0078 基础上）、ADR 0049（真书架）、ADR 0066（token）

## 一、决策

针对 Bookshelf-1.5 确认的 P1（碎片化+空层板）/ P2（整架同色）/ P3（390 缩小版桌面架），
做第二轮视觉结构重设计。数据/API/交互全冻结：`groupBookshelf` / `spineThickness` /
`spineColor` / `spineSeed` / bookshelf.js 零改动；不新增依赖/token/组件体系。

## 二、P1：碎片化 → 视觉合架 + 贴近书本的架面

- **合架规则（视觉层）**：`groupBookshelf` 结果中册数 ≤ 2 的「小分类」连续合进一个
  **共享架「零散藏书」**（同一匣 + 同一条层板，各小组保留 mono 小索引 `RAG · 2` 等，
  标签在书左侧同行）；册数 > 2 的大分类仍为独立 shelf-unit。数据分组/筛选/排序/点击
  /右键/selectMode 全部不变（每本书仍是独立 button，DOM = shared→subgroup→book）。
- **架面贴近书本**：`.shelf-case` `width: fit-content; max-width: 100%`——层板只承托
  实际书本区域，不再出现 900px 层板托 1 本书。
- **实测**：shelf-case/board 数量 15 → **7**（6 大架 + 1 共享架）；页面高度
  **4670px → 2196px**（390：1825px）；TV 架空 36%→21%（641px 匣 506px 书，仅剩
  padding+gap）；单册不再独占全宽空架。

## 三、P2：整架同色 → 标签色相确定性扰动

- `Bookshelf.jsx` 新增纯函数 `spineColorVaried(accent, it)`：在 `spineColor` 标签基色
  上按 `stringHash(it.id)` 做 **±12°** 的确定性色相扰动（同一本书每次渲染同色）。
- 效果：同分类保持相近色系、每本略有差异——TV 22 本从「全部 rgb(185,137,194)」变为
  51/63 本书各自可区分的微差色；非彩虹、非灰。

## 四、P3：390 → 紧凑书架（非缩小版）

- `<640px`：书高度 210→**172px**（仍为实体书，非细柱）；单元间距 30→18px；匣 padding
  收窄；共享架小组间距收紧；书脊最小 24px 保持。页面 4660→**1803px**，首屏 4 架。
- hover preview 极右书修复：`x+120 > vw-8` 时改放书左侧（不再 clamp 出奇怪位置）。

## 五、验证

- vitest **270 passed**（264 + 6 新增：合架不丢书/独立 button、大分类独立架、混合架、
  selectMode+aria-pressed、context menu、颜色 deterministic+±12°+同架有差异）；
  build 通过。
- 真实浏览器（Electron 离屏 + 真实库 63 册，后端 8001 + vite 5173）：
  - 1920/1440/1024/768/390 全 `hOverflow=false`；63 书 / 7 匣 / 7 层板 / 15 小组
    （data-testid 语义）/ 1 共享架；书脊 23–46px（390 min 24、height 172）。
  - hover：最右/最左/最窄/最宽书 preview 均在视口内；390 极右书 preview 移到书左侧
    不截断（修复）；1440 正常右侧。
  - 交互：点击进「作品档案」详情、context menu、selectMode 63 标记 + aria-pressed=1、
    网格 63 卡、列表 3 组，全部正常；无 JS 错误。
  - 截图 `bookshelf2_1920/1440/1024/768/390.png`（真实渲染）。
