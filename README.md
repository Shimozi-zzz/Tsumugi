# Tsumugi

本地优先、轻量级的视觉小说与 PC 单机游戏库管理器。

## 核心特性

- **回廊展架**：支持侧封出盘与展柜视图、系列聚类与多种排序方式、键鼠平滑漫游与状态快筛。
- **多源刮削与单字段替换**：聚合 VNDB、Bangumi、Steam、SteamGridDB、TouchGal 资料与视觉资产，支持封面 / Logo / Hero / 宣传片 PV 与单项元数据定向检索替换。
- **游玩计时与时间账本**：自动追踪游戏进程并持久化每次游玩会话，提供年度热力图、月度分布、作品时长榜与会话明细。
- **历程拼图导出**：按游玩时长分级生成等比模块化 Bento 封面网格，支持自适应海报及多种画幅的高清 PNG 本地导出。
- **全局留声机**：支持检索试听并本地化作品主题曲，在回廊与详情页间无缝淡入淡出播放。
- **Bangumi 单向状态上传**：绑定作品条目 ID 后，可将本地游玩状态单向推送至 Bangumi。
- **WebP 瘦身与存储治理**：入库与在线抓图自动转码压缩为 WebP 并生成缩略图，内置分类磁盘占用分析、存量旧图批量转换与孤儿文件清理。
- **便携与更新检查**：全部数据库与媒体资产保存在单一 `data/` 目录，内置 GitHub Releases 版本检查。

## Windows 便携版使用

1. 前往本仓库 [Releases](https://github.com/Shimozi/tsumugi-platform/releases) 下载最新的 `Tsumugi-Windows-x64-v*.zip`。
2. 解压至任意本地目录，双击 `Tsumugi.exe` 即可启动。
3. 全部数据库、图片、音频、视频与存档备份均保存在 `Tsumugi.exe` 同级的 `data/` 目录中，迁移或升级时保留 `data/` 即可无缝延续数据。

## 本地开发

需要 Python 3.12+（推荐使用 [uv](https://docs.astral.sh/uv/)）与 Node.js 20+。

### 启动后端

```bash
uv sync
uv run uvicorn backend.main:app --reload --reload-dir backend --host 0.0.0.0 --port 8000
```

### 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端开发服务默认运行在 `http://localhost:5173`，并将 `/api` 与 `/static` 请求代理至本地 `8000` 端口。

### 本地生产模式 / 桌面窗口调试

```bash
# 构建前端静态产物
cd frontend && npm ci && npm run build && cd ..

# 浏览器单端口访问（http://127.0.0.1:8000）
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000

# 或安装可选桌面依赖后拉起原生窗口（推荐在 Windows 环境下运行）
uv sync --extra desktop
uv run --extra desktop python desktop.py
```

### 构建 Windows 便携版

```powershell
cd frontend; npm ci; npm run build; cd ..
uv sync --extra desktop
uv run --extra desktop python packaging/build_windows.py
```

打包产物位于 `dist/Tsumugi/`。推送 `v*` 格式标签（如 `git tag v0.9.0 && git push origin v0.9.0`）也会自动触发 GitHub Actions 编译并发布 Windows 便携压缩包。
