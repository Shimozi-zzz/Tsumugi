# 0049 · 真书架（P5，对 ADR 0019 的有意推翻）

日期：2026-08-10
状态：已接受
基准：AGENT_UI.md v2.2【图书馆·Book Shelf】+ docs/decisions/0019-bookshelf-view.md + PROJECT_AUDIT P5

## 一、范围

把书架从"书脊列表"（ADR 0019：一排窄书脊）升级为**真书架**：层板线、按主标签分架、
书脊厚度来自数据、hover 取书浮起。纯前端改动（`bookshelf.js` / `Bookshelf.jsx` /
`index.css`），后端零改动。

**本轮明确不做（推迟）**：首页"最近记忆"（现有首页已通过猫娘台词/往年今日呈现记忆，
再加记忆条有违神殿入口的极简；属后续打磨）；"去除工具感"的 Inspector/热力图收敛
（持续性的 UI 纪律，非一次性改动）。

## 二、核心决策（对 ADR 0019 的有意推翻）

ADR 0019 当时选择"书脊按标签哈希配色 + 单排平铺"（书脊列表）。P5 **有意推翻**其布局
部分，**保留**其配色决策：

1. **保留**：书脊配色仍按主标签哈希（`spineColor`/`spineSeed`，ADR 0019），同标签相近
   色相；ADR 0037 的书脊 hover 取色联动（CoverAmbient）保留。
2. **推翻/新增（布局 → 空间）**：
   - **层板线（shelf line）**：每层书下方一条书架板（`--surface-1/2` 渐变 + 下边框），
     书"站"在层板上，有地面感；
   - **按主标签分架**：`groupBookshelf` 把条目按 `primaryTag` 分到各层（每层一个分类
     标签 + 册数），"未分类"排最后、数量多的层靠前；
   - **书脊厚度来自数据**：`spineThickness` 由正文长度（无正文用 chunk 数）决定，9~28px
     钳制——"这本书有多厚"；
   - **hover 取书浮起**：`.shelf-book:hover { transform: translateY(-5px) }` + 保留抽书预览。

理由：v1.1 / AGENT_UI 都要求书架是"真实书架的空间隐喻"而非"书脊贴成的列表"；真实书架
的层板/厚度/取书让收藏空间有体积感，是"进入自己的收藏空间"的核心体验。

## 三、接口/实现

- `bookshelf.js`：新增 `spineThickness(it)`、`groupBookshelf(items)`（纯函数，可测）；
- `Bookshelf.jsx`：渲染改为 分架组（标签 + 册数 + 一层书 + 层板线），书脊宽 = 厚度、
  高 210、hover 浮起；保留 点击进详情 / 选择模式 / 右键 / 抽书预览；
- `index.css`：`.shelf-book` 过渡 + hover 浮起。

## 四、测试与实测

- vitest **210 passed**（+3：spineThickness 钳制/无正文兜底、groupBookshelf 分架排序、
  真书架分架渲染 + 层板线 + 浮起类）；原有 14 例 bookshelf 测试全兼容（title/hover/
  视图切换/筛选）。
- 实测见简报（真实库书架视图：按标签分层 + 层板线 + 书脊厚度差异，截图）。
