"""配置管理模块 - 从环境变量/.env 加载"""
import os

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。全部字段有默认值，缺少 DEEPSEEK_API_KEY 时应用仍可启动，
    调用 LLM 接口时才报错（便于开发与测试）。"""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- DeepSeek API ----
    # SecretStr：避免 repr/日志/异常信息中泄露明文密钥
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_api_base: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    llm_timeout: float = 60.0
    llm_max_retries: int = 1

    # ---- 数据库 ----
    database_url: str = "sqlite:///./tsumugi.db"

    # ---- 服务端口 ----
    # 后端统一端口，从环境变量 TSUMUGI_PORT 读取；8000 在部分 Windows 机器上
    # 被系统保留端口占用，故默认 8001。前端/Electron 读取同一环境变量。
    tsumugi_port: int = 8001

    # ---- Chroma 向量库 ----
    chroma_persist_directory: str = "./data/chroma"
    chroma_collection: str = "tsumugi"

    # ---- 文档切分 ----
    chunk_size: int = 512
    chunk_overlap: int = 64

    # ---- 检索 ----
    top_k: int = 5
    # 每个 Item 最多保留多少个 chunk 进入最终结果（去重，保证结果多样性）
    max_chunks_per_item: int = 1

    # ---- RAG / prompt ----
    # 上下文总长度上限（字符数，中文按字符计）
    max_context_length: int = 4000

    # ---- Embedding ----
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    # HuggingFace 模型下载端点；默认指向镜像以便在国内网络可下载
    hf_endpoint: str = "https://hf-mirror.com"

    # ---- 上传文件 ----
    upload_dir: str = "./data/uploads"
    # 外部封面图本地缓存目录（收藏入库时缓存一份，避免外链失效/带宽）
    thumbnails_dir: str = "./data/thumbnails"


settings = Settings()

# 在 sentence-transformers/transformers 被导入前生效
os.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint)
# NLTK 3.10+ 的安全导入钩子会把"venv 位于项目目录内"误判为 CWD 攻击
os.environ.setdefault("NLTK_DISABLE_IMPORT_SECURITY", "1")
