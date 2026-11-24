import asyncio
from contextlib import asynccontextmanager
import logging
import mimetypes

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api import (
    collections,
    games,
    import_external,
    library_tools,
    media,
    scraper,
    settings,
    stats,
    system,
)
from backend.core.config import (
    APP_VERSION,
    DATA_DIR,
    DB_PATH,
    FRONTEND_DIST_DIR,
    ensure_data_dirs,
)
from backend.core.os_adapter import os_adapter
from backend.db.database import AsyncSessionLocal, get_db, init_db
from backend.db.models import GameMediaPath
from backend.services.backup_service import create_auto_snapshot
from backend.services.process_tracker import process_tracker
from backend.services.thumbnail_service import prewarm_cover_thumbnails

logger = logging.getLogger("tsumugi.main")

# 屏蔽 Windows 注册表 MIME 污染（避免 .js 被识别为 text/plain 导致 WebView2 拒绝执行 ES Module 黑屏）
mimetypes.init()
for _ext, _mime in (
    (".js", "application/javascript"),
    (".mjs", "application/javascript"),
    (".css", "text/css"),
    (".svg", "image/svg+xml"),
    (".webp", "image/webp"),
    (".woff2", "font/woff2"),
    (".json", "application/json"),
):
    mimetypes.add_type(_mime, _ext, strict=True)

# 在 StaticFiles 挂载前确保可写 data/ 目录存在，避免启动报错
ensure_data_dirs()


async def _background_prewarm_thumbnails() -> None:
    """后台低优先级预热现有游戏库本地封面的 sm (360px) WebP 缩略图，避免阻塞启动"""
    try:
        await asyncio.sleep(0.35)
        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    select(GameMediaPath.cover_path).where(GameMediaPath.cover_path != "")
                )
            ).scalars().all()
        cover_paths = [str(p).strip() for p in rows if p and str(p).strip()]
        if not cover_paths:
            return
        stats = await asyncio.to_thread(prewarm_cover_thumbnails, cover_paths, size="sm")
        logger.info("Background thumbnail prewarm finished: %s", stats)
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.debug("Background thumbnail prewarm skipped: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # 启动完成后按 10 分钟节流策略自动执行 SQLite 在线热备快照（最多保留 5 份）
    try:
        snap = await asyncio.to_thread(create_auto_snapshot, tag="auto", force=False)
        if snap:
            logger.info("Startup SQLite auto-snapshot created: %s", snap["filename"])
    except Exception as exc:
        logger.warning("Startup SQLite auto-snapshot skipped: %s", exc)

    prewarm_task = asyncio.create_task(_background_prewarm_thumbnails())
    try:
        yield
    finally:
        if not prewarm_task.done():
            prewarm_task.cancel()
            try:
                await prewarm_task
            except asyncio.CancelledError:
                pass
        # 应用关闭时强制落盘尚未写入的游玩时长
        await process_tracker.shutdown_flush()


app = FastAPI(
    title="Tsumugi Local Game Library API",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 将本地 data/ 目录挂载为静态资源路径（如 /static/data/assets/1/cover_thumb.webp）
app.mount("/static/data", StaticFiles(directory=str(DATA_DIR)), name="static_data")

# 统一注册全部业务模块路由
app.include_router(games.router)
app.include_router(settings.router)
app.include_router(media.router)
app.include_router(scraper.router)
app.include_router(library_tools.router)
app.include_router(import_external.router)
app.include_router(stats.router)
app.include_router(collections.router)
app.include_router(system.router)
app.include_router(system.tasks_router)


@app.get("/api/health", tags=["System"])
async def health_check(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT name FROM sqlite_master WHERE type='table';"))
    tables = [row[0] for row in result.fetchall()]
    return {
        "status": "ok",
        "os_adapter": os_adapter.platform_name,
        "db_file": str(DB_PATH),
        "initialized_tables": tables,
        "frontend_dist_ready": (FRONTEND_DIST_DIR / "index.html").is_file(),
        "running_game": process_tracker.get_status(),
    }


# 生产/桌面便携态：若 frontend/dist 存在且含 index.html，托管静态资源并兜底 SPA 路由
_FRONTEND_INDEX = FRONTEND_DIST_DIR / "index.html"
_FRONTEND_ASSETS = FRONTEND_DIST_DIR / "assets"

if _FRONTEND_INDEX.is_file() and _FRONTEND_ASSETS.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=str(_FRONTEND_ASSETS)),
        name="frontend_assets",
    )


# 显式拦截所有未匹配的 /api/* 任意 HTTP 方法请求，直接返回 404
# （避免 POST/PUT/DELETE 等 API 路径落到下方的 @app.get("/{full_path:path}") 而误报 405 Method Not Allowed）
@app.api_route(
    "/api",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
@app.api_route(
    "/api/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def api_not_found_fallback(full_path: str = ""):
    raise HTTPException(status_code=404, detail="Not Found")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa_frontend(full_path: str):
    if (
        full_path in ("docs", "redoc", "openapi.json")
        or full_path.startswith(("api/", "static/", "docs/", "redoc/"))
        or full_path == "api"
    ):
        raise HTTPException(status_code=404, detail="Not Found")

    if not _FRONTEND_INDEX.is_file():
        return {
            "app": "Tsumugi Local Game Library Backend",
            "version": APP_VERSION,
            "message": "前端尚未构建（frontend/dist 不存在）。开发模式请访问 Vite 服务，或运行 npm run build。",
            "docs": "/docs",
        }

    # 若命中 frontend/dist 下真实文件（如 favicon.ico / favicon.svg），直接返回该文件
    if full_path:
        dist_root = FRONTEND_DIST_DIR.resolve()
        candidate = (FRONTEND_DIST_DIR / full_path).resolve()
        if candidate.is_relative_to(dist_root) and candidate.is_file():
            return FileResponse(candidate)

    return FileResponse(_FRONTEND_INDEX)
