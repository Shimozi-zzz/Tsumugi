"""向量库访问层 - 统一封装 Chroma 客户端与 collection"""
import chromadb

from app.config import settings

_client = None


def get_chroma_client():
    """懒加载 PersistentClient 单例。禁用遥测避免第三方上报噪音。"""
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=settings.chroma_persist_directory,
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
    return _client


def get_collection():
    """获取/创建向量集合，使用余弦距离。"""
    return get_chroma_client().get_or_create_collection(
        name=settings.chroma_collection,
        metadata={"hnsw:space": "cosine"},
    )
