"""FastAPI 应用入口"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.connectors import persistence as connector_persistence
from app.connectors import registry as connector_registry
from app.database import Base, engine, ensure_schema
from app.api.routes import router
import app.models  # noqa: F401  确保 ORM 模型注册到 metadata

# 把 .env（含 UI 直接填 Key 写入的 TSUMUGI_API_KEY_* 等）加载进 os.environ，
# 使环境变量占位符 {VAR} 在重启后仍能解析（pydantic-settings 只读 Settings 字段）
load_dotenv()

# 确保数据目录存在
os.makedirs(settings.upload_dir, exist_ok=True)
os.makedirs(settings.chroma_persist_directory, exist_ok=True)
os.makedirs(settings.thumbnails_dir, exist_ok=True)
os.makedirs(settings.plugins_dir, exist_ok=True)

Base.metadata.create_all(bind=engine)
ensure_schema()  # 旧库补列（如 content_hash）

# 存量 Review → Memory 补生成（幂等；让旧书评也出现在作品时间轴，ADR 0041/0042）
import app.memories as _memories  # 函数内 import：避免启动期循环依赖（memories 依赖 models）
_memories.backfill_reviews(engine)

# 存量外部条目 → 世界轴列幂等回填（work_type/原名/发行，只填 NULL，ADR 0045）
import app.work_model as _work_model
_work_model.backfill_work_columns(engine)

# 存量外部条目 → Collection 行幂等回填（status 从 Bangumi 导入 Review 迁移，ADR 0046）
import app.collections as _collections
_collections.backfill_collections(engine)

# 存量外部条目 → Character 角色索引重建（P4 / ADR 0048）
import app.characters as _characters
_characters.backfill_characters(engine)

# 存量直接 Memory → 向量补齐（P7 / ADR 0051：个人语义检索）
import app.memories as _memories
_memories.backfill_memory_vectors(engine)

# 发现并注册内置 Connector（如 bangumi）
connector_registry.discover()

# 从 sources 表恢复用户配置的声明式数据源（Phase 4）
for config in connector_persistence.load_declarative_configs():
    try:
        enabled = config.pop("_enabled", True)
        connector_registry.register_declarative(config, enabled=enabled)
    except ValueError as e:
        print(f"[connector] 恢复声明式数据源 {config.get('name')} 失败：{e}")

# 应用各 Connector 的通用设置（出站代理）
connector_registry.apply_settings(connector_persistence.get_connector_settings())

# 加载本地代码级插件（ADR 0027：用户手动放入 plugins/ 目录；单插件失败不阻塞）
from app import plugins as plugin_loader
plugin_loader.load_plugins()

app = FastAPI(
    title="Tsumugi RAG System",
    description="个人知识库语义搜索与问答系统",
    version="0.1.0",
)

# 允许的来源：Web(Vite dev) 与 Electron 客户端（file:// 下 Origin 为 "null"）。
# 不用 "*" + credentials 的组合（不规范）。
_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "null",  # Electron 以 file:// 加载页面时的 Origin
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api", tags=["api"])

# 静态文件服务：上传图片与缩略图（供前端 <img> 加载）
# 路径约定：Item.file_path 存 "./data/uploads/xxx" 或 "./data/thumbnails/xxx"，
# 前端据此拼成 /static/... 访问。
os.makedirs(settings.upload_dir, exist_ok=True)
os.makedirs(settings.thumbnails_dir, exist_ok=True)
app.mount("/static/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")
app.mount("/static/thumbnails", StaticFiles(directory=settings.thumbnails_dir), name="thumbnails")


@app.get("/")
async def root():
    return {
        "message": "Tsumugi RAG System is running",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    # 端口统一走 settings.tsumugi_port（环境变量 TSUMUGI_PORT）
    uvicorn.run(app, host="0.0.0.0", port=settings.tsumugi_port)
