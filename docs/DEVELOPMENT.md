[← 返回首页 README](../README.md)

# Tsumugi 开发者文档

本文档面向本地开发、调试与 Windows 安装包构建。

---

## 技术栈与架构

- **前端界面**：Vue 3 (Composition API) + TypeScript + Vite + Pinia + `hls.js`
- **后端服务**：Python 3.12+（`uv` 管理）、FastAPI、SQLAlchemy 2.0 (Async) + `aiosqlite`、Pydantic v2、`httpx` (0.28+)、Pillow、`psutil`、`pypinyin`、`yt-dlp`
- **本地存储**：SQLite 单文件数据库 + 本地媒体文件目录（统一存放于可写 `data/`）
- **桌面封装**：PyWebView（Windows WebView2 无边框窗口 + 原生桥接）
- **构建发布**：PyInstaller（`--onedir`）+ Inno Setup 6（`Tsumugi-Setup-*.exe`）+ GitHub Actions

运行形态分为两种：
- **开发模式**：后端 `uvicorn` 监听 `8000`，前端 Vite 监听 `5173` 并代理 `/api` 与 `/static`；
- **桌面/生产模式**：FastAPI 托管编译后的 `frontend/dist`，桌面入口 `desktop.py` 在守护线程拉起内置服务（随机本地空闲端口）并打开原生 WebView2 窗口；冻结态下程序只读资源位于 `BUNDLE_DIR`（`sys._MEIPASS`），可写数据位于可执行文件同级 `data/`（支持 `TSUMUGI_DATA_DIR` 覆盖）。

---

## 项目目录结构

```text
.
├── backend/                  # FastAPI 后端源码
│   ├── api/                  # REST 路由（games / media / scraper / stats / settings / collections / system）
│   ├── core/                 # 路径配置（config.py）与跨平台启动适配（os_adapter.py）
│   ├── db/                   # SQLAlchemy 模型与无损自动迁移（database.py）
│   ├── scrapers/             # VNDB / Bangumi / Steam / SteamGridDB / TouchGal / Bilibili 刮削与聚合
│   ├── services/             # 资产下载、WebP 压缩、存档备份、进程计时与后台任务队列
│   └── main.py               # FastAPI 入口、MIME 覆写与前端静态托管
├── frontend/                 # Vue 3 + TypeScript 前端工程
│   ├── public/               # 静态图标等公共资源
│   └── src/                  # 视图（回廊 / 详情页）、弹窗组件、Pinia Store 与 Bento 拼图算法
├── packaging/                # Windows 打包脚本与资源
│   ├── build_windows.py      # PyInstaller 打包脚本（输出 dist/Tsumugi/）
│   ├── installer.iss         # Inno Setup 6 安装包脚本（输出 release_assets/Tsumugi-Setup-*.exe）
│   └── tsumugi.ico           # Windows 多尺寸应用图标
├── .github/workflows/        # GitHub Actions 自动构建与发布工作流（release.yml）
├── desktop.py                # PyWebView 单进程桌面入口（无边框窗口、托盘/全屏控制桥接）
├── docs/                     # 开发文档与截图资源
└── pyproject.toml            # Python 依赖声明（含可选桌面依赖组 desktop）
```

---

## 本地开发启动指南

环境要求：Python 3.12+（推荐 [uv](https://docs.astral.sh/uv/)）与 Node.js 20+。

### 1. 启动后端

```bash
uv sync
uv run uvicorn backend.main:app --reload --reload-dir backend --host 0.0.0.0 --port 8000
```

### 2. 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问 `http://localhost:5173`，接口文档位于 `http://127.0.0.1:8000/docs`。

### 3. 本地桌面端调试（推荐在 Windows 下运行）

先构建前端静态产物，再安装可选桌面依赖组 `desktop` 并启动 `desktop.py`：

```powershell
cd frontend
npm ci
npm run build
cd ..

uv sync --extra desktop
uv run --extra desktop python desktop.py
```

#### 调试环境变量

| 环境变量 | 说明 |
| --- | --- |
| `TSUMUGI_DEBUG=1` | 开启更详细的调试输出（日志默认同步写入 `data/tsumugi.log`） |
| `TSUMUGI_DATA_DIR` | 指定自定义数据目录路径（默认开发态为 `./data`，冻结态为 `Tsumugi.exe` 同级 `data/`） |
| `TSUMUGI_VERSION` | 覆盖当前上报的应用版本号（默认读取 `backend/core/config.py` 中的 `APP_VERSION`） |
| `TSUMUGI_GITHUB_REPO` | 覆盖检查更新使用的 GitHub 仓库（格式 `owner/repo`） |

---


