# 0027 · 第三方插件系统：本地文件加载 + 开源信任模型

日期：2026-08-08
状态：已接受

## 一、本次决策的背景：对"禁止代码级插件"的重新评估

AGENTS.md 早期明确反对代码级 Connector 插件（"建议走声明式配置而不是执行任意
Python 代码；确需代码级插件时要有沙箱/权限清单机制"）。本轮**有意放开这一限制**，
允许代码级插件，但绑定一个严格信任模型。这不是意外推翻，而是有意识的架构决策，
权衡过程记录如下：

**为什么改变之前"只用声明式"的决定**：
1. 声明式配置（HTTP 端点 + 字段映射）只覆盖"简单 GET 检索"这类场景。真实数据源
   往往需要：POST 请求体（VNDB）、OAuth 鉴权、多端点组合（Bangumi 详情+角色）、
   特殊编码（萌娘百科）、请求缓存/限流编排。把这些都塞进声明式配置，配置本身会
   膨胀成"图灵不完备的迷你语言"，比直接给一份可读的 Python 更难看懂、更难审查。
2. 本项目**计划开源**，用户/贡献者可以自行审查代码。既然代码本身可审查、可审计，
   "禁止任意代码"的收益（防恶意代码）在"代码可被任何人审查"的前提下被大幅稀释，
   而损失（插件能力受限、维护成本高）却是实打实的。
3. 内置 Connector 本来就是 Python 实现（app/connectors/ 下每个数据源一个子目录 +
   manifest.json）。把同一套约定开放给第三方，是"内置 → 插件"的自然泛化，而不是
   引入一个全新的执行机制。

**为什么不做沙盒**：如实评估——为个人项目做一个真正安全的沙盒工程量巨大
（进程隔离/RestrictedPython/能力限制+逃逸审计），而且很容易做出"看似安全实则可
绕过"的假沙盒，**比不做沙盒但如实告知风险更危险**（用户会误以为被隔离保护）。
因此本轮不做隔离，插件与后端完全同权限，风险用**用户可见**的方式暴露。

## 二、信任模型：本地文件加载（本决策最重要的设计约束）

```
✅ 允许：用户从 GitHub/社区下载插件 .py → 手动放进 plugins/ 目录 → 重启应用 → 加载
❌ 禁止：应用内置"插件市场 / 一键远程安装并自动运行"
❌ 不做：沙盒隔离、自动更新、静态安全扫描
```

**为什么选"本地文件"而非"远程市场"作为信任边界**：
- 远程市场 = 应用在运行时从不可信网络拉取任意代码并自动执行，这是**不可审计**
  的信任跳跃：用户无法在点击安装前审查将要运行的代码，供应链上也天然隐含
  "市场运营方可投毒"的风险。个人项目没有能力运营可信市场。
- 本地文件 = 信任的**决策点**回到用户手里：放入文件这一步本身就是"我审查过、
  我信任"的显式动作；代码始终在本地磁盘上，任何时刻可被重新审查/删除。
- 这符合开源项目的审查文化：问题不在于"禁止执行代码"，而在于"执行的决策必须
  是用户主动、可审查的"。

## 三、插件加载机制

- 目录约定：`plugins/` 下每个插件是一个子目录，含 `manifest.json` + `connector.py`
  （暴露 `build_connector()` 工厂函数），与内置 Bangumi/萌娘百科/VNDB 同构；
  **以 `_` 或 `.` 开头的目录跳过**（`plugins/_template/` 是可复制的参考示例，不会
  被自动加载）；`settings.plugins_dir` 可配（默认 `./plugins`）。
- 加载：`app/plugins.load_plugins()` 在应用启动时扫描（main.py 在 discover() 与
  声明式恢复之后调用）。用 `importlib.util.spec_from_file_location` 以独立模块名
  加载任意路径的 .py（插件内用绝对导入 `from app.connectors.base import ...`）。
- **身份/能力权威 = manifest.json**：加载后覆盖 `connector.name`/`connector.manifest`，
  插件作者无需在代码里再造 manifest；声明 `get_detail` 能力则强制要求实现该方法。
- **优雅降级**：任何单个插件失败（语法错误/缺 build_connector/返回 None/缺 search/
  缺 get_detail/名字冲突/manifest 非法）都被捕获，记录 `[plugin] 加载 <目录> 失败：
  <原因>` 日志 + 写入 failures 列表（设置页可见），**不影响其它插件与应用启动**。
- 注册：`registry.register_plugin()`（origin="plugin"），与内置/声明式统一进
  `get_enabled_connectors()`，因此**自动参与联合检索、收藏入库、角色墙**等既有流程，
  无需改动检索编排代码。

## 四、风险提示（必须做）

1. **设置页「插件」面板**（新增 settings tab）：列出已加载插件，每个插件旁醒目
   标注"⚠️ 第三方插件拥有与本应用相同的系统权限，请仅安装你信任的来源"；同时
   展示加载失败列表（便于排查，不阻塞）。
2. **一次性风险确认**：首次检测到 plugins/ 目录有插件时，设置页出现醒目风险横幅
   （说明同权限/无沙盒/不联网下载），点击"我已了解，不再提示"后持久化（sources 表
   `plugin_notice` 行），之后不再打扰；确认前 `notice_needed=true` 由 /plugins 暴露。
3. **文档安全声明**：`plugins/README.md` 开头即是醒目的安全声明，插件开发文档中
   亦有"安全注意事项"章节；`/connectors` 返回 `origin` 供前端标识。

## 五、明确不做

- 不做沙盒/权限隔离（理由见第一节）；
- 不做应用内插件市场 / 一键远程安装；
- 不做插件自动更新；
- 不做静态安全扫描。

## 六、测试与实测

- pytest **358 passed**（新增 13 个插件用例：正常加载、语法错误跳过、缺
  build_connector、返回 None、缺 search、声明 get_detail 未实现、名字冲突、
  manifest 非法、`_` 前缀目录跳过、无插件目录、端到端联合检索、/plugins +
  /connectors(origin) + acknowledge）；覆盖率 86.0%；前端 build 通过、vitest 88。
- **实测（真实 plugins/ 目录 + 真实 API）**：
  1. 在 `plugins/` 放入真实最小插件 `hello_world`（GitHub 搜索）+ 故意写错语法
     的 `bad_syntax`，重启应用 → `hello_world` 被加载（origin=plugin），
     `bad_syntax` 优雅跳过并记录 `[plugin] 加载 bad_syntax 失败：'(' was never
     closed (connector.py, line 2)`，**应用正常启动、health 正常**；
  2. `GET /plugins`：loaded=[hello_world]、failures=[bad_syntax]；`GET /connectors`：
     hello_world origin=plugin、enabled；
  3. `hello_world.search("rag")` → 5 条真实 GitHub 结果；
  4. `POST /search/federated`（真实并发全部数据源）→ hello_world 出现在结果中，
     与 bangumi/moegirl/vndb 并列，errors={}；
  5. 风险确认：acknowledge 前 notice_needed=true，确认后 false（一次性）。
  - 实测中发现 Open Library 在本机网络间歇不可达，改用更稳定的 GitHub 搜索 API
    做实测插件；`plugins/_template/hello_world`（提交的文档示例）仍用 Open
    Library 作"最小可复制"范例。
  - 实测用插件（hello_world/bad_syntax）为临时文件（gitignored），验证后已删除；
    仓库只保留 plugins/README.md 与 plugins/_template/ 参考示例。
