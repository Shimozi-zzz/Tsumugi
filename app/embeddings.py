"""Embedding 模块 - 统一管理 embedding 模型（懒加载单例）"""
import threading
from typing import List

from app.config import settings


class EmbeddingError(Exception):
    """embedding 模型加载或推理失败。"""


_model = None
_model_lock = threading.Lock()


def get_embedding_model():
    """懒加载 SentenceTransformer 模型并缓存（进程内单例）。"""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                    _model = SentenceTransformer(settings.embedding_model)
                except Exception as e:  # 网络失败 / 模型损坏 / 内存不足等
                    raise EmbeddingError(
                        f"加载 embedding 模型 '{settings.embedding_model}' 失败：{e}"
                    ) from e
    return _model


def embed_texts(texts: List[str]) -> List[List[float]]:
    """批量生成文本向量（归一化，可直接用余弦相似度）。"""
    if not texts:
        return []
    model = get_embedding_model()  # 可能抛 EmbeddingError
    try:
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=False,
        )
    except Exception as e:
        raise EmbeddingError(f"embedding 生成失败：{e}") from e
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> List[float]:
    """生成单个查询向量。"""
    return embed_texts([text])[0]
