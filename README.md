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
- **独立数据目录与更新检查**：全部数据库与媒体资产保存在安装目录同级的 `data/` 文件夹，内置 GitHub Releases 版本检查。

## Windows 安装与升级

1. 前往本仓库 [Releases](https://github.com/Shimozi/tsumugi-platform/releases) 下载最新的 **`Tsumugi-Setup-v*.exe`**。
2. 双击安装包按向导完成安装（免管理员权限，支持自定义安装目录，默认安装至 `%LOCALAPPDATA%\Programs\Tsumugi`）。
3. **无损覆盖升级**：新版本发布后，直接下载新版 `Tsumugi-Setup-*.exe` 覆盖安装到原目录即可；安装器会自动关闭运行中的程序，且升级与卸载均不会删除安装目录下的 `data/` 数据文件夹。

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

### 构建 Windows 安装包

需要已安装 [Inno Setup 6](https://jrsoftware.org/isinfo.php)（`ISCC.exe`）：

```powershell
cd frontend; npm ci; npm run build; cd ..
uv sync --extra desktop
uv run --extra desktop python packaging/build_windows.py
ISCC.exe /DAppVersion=0.9.0 /DReleaseTag=v0.9.0 packaging/installer.iss
```

最终安装包产出在 `release_assets/Tsumugi-Setup-v0.9.0.exe`。推送 `v*` 格式标签（如 `git tag v0.9.0 && git push origin v0.9.0`）也会自动触发 GitHub Actions 编译并发布单文件 `.exe` 安装包。
