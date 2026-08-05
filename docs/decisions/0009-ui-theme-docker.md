# 0009 · UI 自定义与部署打磨（Phase 5）

日期：2026-08-05
状态：已接受（Phase 5）

## 决策

### 主题系统（CSS 变量）

- 基于 **CSS 变量**实现多主题，`html[data-theme]` 切换，零 JS 运行时依赖：
  - `:root/default`（默认）、`shosai`（书斋，深色纸墨）、`spring`（樱）、
    `summer`（青空）、`autumn`（枫）、`winter`（雪）。
- 变量集：`--bg/--panel/--panel-border/--text/--text-secondary/--accent/
  --accent-hover/--accent-soft/--danger/--ok/--tag-bg/--tag-text/--input-bg/
  --input-border`。
- 前端 `themes.js`：`loadTheme/applyTheme`，选择存 `localStorage`。
- App 组件从硬编码 Tailwind 色（stone/indigo/emerald）改为 `tsm-*` 类映射
  到 CSS 变量，主题切换即整体换肤。

### 仪表盘布局（可增删/排列面板）

- `layout.js`：面板清单 + `loadPanelOrder/savePanelOrder`（localStorage）。
- 每个面板（导入/提问/资料库/标签）可**收起/移除**，被移除的面板显示在
  底部可一键重新添加，顶栏"重置布局"恢复默认。
- `components/Panel.jsx`：通用面板壳（标题 + 收起/移除按钮）。

### 前端细节改进

- 错误分区：导入错误与问答错误分离（`uploadError` / `askError`），不再
  混用一个顶部红条。
- 来源角标：`external_ref` 条目显示 `source` 徽标（Phase 3 联合检索角标
  需求的前端落地）。

### Docker

- `Dockerfile`：python:3.12-slim + 系统 build 依赖（chromadb）+
  requirements + app；`CMD uvicorn 单进程`（embedding 常驻内存，多进程会
  重复加载模型）。
- `docker-compose.yml`：backend（挂载 ./data 持久化，env_file .env，
  DATABASE_URL/CHROMA/UPLOAD 指向容器路径）+ frontend（nginx 静态服务，
  nginx.conf 代理 /api → backend:8001，SSE 关缓冲）。
- 说明：本机未装 Docker，未实测构建；文件按标准模式编写，待有 Docker 环境
  验证。

### CI 打磨

- pytest.ini 增加 `--cov=app --cov-report=term-missing --cov-fail-under=70`
  （覆盖率门槛 70%，当前 82%）。
- CI 后端 job 的 `pytest -q` 自动带上覆盖率并强制门槛。

## 权衡

- 主题用 CSS 变量而非 Tailwind 配置动态类：CSS 变量运行时切换开销最小、
  主题是纯声明式（便于用户自定义新主题）。
- 面板布局用 localStorage 而非后端存储：纯前端偏好，无需 API/迁移。
- Docker 用单 uvicorn 进程：避免多进程重复加载 embedding 模型（内存与
  首次加载时间都翻倍）。

## 已知限制

- Docker 未在本机验证（无 docker）；Dockerfile 依赖 HF 下载模型，容器需
  网络可达（可用 HF_ENDPOINT 镜像）。
- 主题切换在 Electron file:// 下经 localStorage 正常（Chromium 支持）。
- 面板布局无拖拽排序（仅增删/重置）；拖拽需第三方库，留待后续。
