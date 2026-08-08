"""Review 读后感/书评模块

Review 内容接入 RAG 检索的方案（详见 docs/decisions/0010-review-rag.md）：
- 复用现有 Chunk 切分 + embedding + Chroma 机制；
- Chunk 表加 `review_id` 列区分"条目自身内容"(NULL) 与"某条 review 内容"；
- Chroma metadata 带 `item_id` + `review_id`，检索时可区分来源；
- 编辑/删除 review 时按 chunk 的 embedding_ref 反向删除向量
  （复用 ingest.py 的"反向清理"模式，避免孤儿向量）。
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app import embeddings, vectorstore
from app.ingest import split_text
from app.models import Chunk, Item, Review

REVIEW_STATUSES = ["想看", "在看", "看完", "搁置", "弃坑"]


def _session():
    # 函数体内 import：与 routes._ingest_sync / connectors.persistence 一致，
    # 测试 patch 时能覆盖（避免模块顶层固化旧引用的坑）
    from app.database import SessionLocal
    return SessionLocal()


def _chunk_ids(review: Review, n: int) -> List[str]:
    return [f"review{review.id}_chunk{i}" for i in range(n)]


def _write_review_vectors(db: Session, review: Review) -> None:
    """把 review.content 切分 -> embedding -> 写入 Chroma + Chunk 行。
    复用 ingest 的反向清理模式：失败时按已写入的 ids 删除 Chroma。"""
    chunks = split_text(review.content)
    if not chunks:
        return
    vectors = embeddings.embed_texts(chunks)  # 可能抛 EmbeddingError
    ids = _chunk_ids(review, len(chunks))
    metadatas = [
        {
            "item_id": review.item_id, "review_id": review.id, "chunk_index": i,
            "source_type": "review",
        }
        for i in range(len(chunks))
    ]
    vectorstore.get_collection().add(
        ids=ids, embeddings=vectors, documents=chunks, metadatas=metadatas,
    )
    for i, (content, ref) in enumerate(zip(chunks, ids)):
        db.add(Chunk(
            item_id=review.item_id, review_id=review.id,
            content=content, chunk_index=i, embedding_ref=ref,
            source_type="review",
        ))


def _delete_review_vectors(db: Session, review: Review) -> None:
    """删除某条 review 关联的全部向量与 Chunk 行（编辑/删除时调用）。"""
    refs = [c.embedding_ref for c in review.chunks if c.embedding_ref]
    if refs:
        try:
            vectorstore.get_collection().delete(ids=refs)
        except Exception:
            pass  # 向量清理失败不阻塞元数据操作，与 ingest 一致
    for c in review.chunks:
        db.delete(c)


def create_review(
    item_id: int,
    content: str,
    title: Optional[str] = None,
    rating: Optional[int] = None,
    status: Optional[str] = None,
    spoiler: bool = False,
    font_size: Optional[int] = None,
    db: Optional[Session] = None,
) -> Review:
    """创建一条 review 并写入向量。"""
    if status is not None and status not in REVIEW_STATUSES:
        raise ValueError(f"status 必须是 {REVIEW_STATUSES} 之一")
    if rating is not None and not (0 <= rating <= 10):
        raise ValueError("rating 必须在 0-10 之间")

    own_session = db is None
    db = db or _session()
    try:
        item = db.get(Item, item_id)
        if item is None:
            raise ValueError(f"item {item_id} 不存在")

        review = Review(
            item_id=item_id, title=title, content=content,
            rating=rating, status=status, spoiler=1 if spoiler else 0,
            font_size=font_size,
        )
        db.add(review)
        db.flush()  # 拿到 review.id

        try:
            _write_review_vectors(db, review)
            db.commit()
            db.refresh(review)
            return review
        except Exception:
            db.rollback()
            # 反向清理已写入的向量（复用 ingest 的孤儿向量防御模式）
            if review.id:
                try:
                    refs = [c.embedding_ref for c in db.query(Chunk)
                            .filter(Chunk.review_id == review.id).all() if c.embedding_ref]
                    if refs:
                        vectorstore.get_collection().delete(ids=refs)
                except Exception:
                    pass
            raise
    finally:
        if own_session:
            db.close()


def update_review(
    review_id: int,
    content: Optional[str] = None,
    title: Optional[str] = None,
    rating: Optional[int] = None,
    status: Optional[str] = None,
    spoiler: Optional[bool] = None,
    font_size: Optional[int] = None,
    db: Optional[Session] = None,
) -> Review:
    """编辑 review：内容变化时删除旧向量并重新写入。"""
    if status is not None and status not in REVIEW_STATUSES:
        raise ValueError(f"status 必须是 {REVIEW_STATUSES} 之一")
    if rating is not None and not (0 <= rating <= 10):
        raise ValueError("rating 必须在 0-10 之间")

    own_session = db is None
    db = db or _session()
    try:
        review = db.get(Review, review_id)
        if review is None:
            raise ValueError(f"review {review_id} 不存在")

        content_changed = content is not None and content != review.content
        if content is not None:
            review.content = content
        if title is not None:
            review.title = title
        if rating is not None:
            review.rating = rating
        if status is not None:
            review.status = status
        if spoiler is not None:
            review.spoiler = 1 if spoiler else 0
        if font_size is not None:
            review.font_size = font_size

        try:
            if content_changed:
                _delete_review_vectors(db, review)
                db.flush()
                _write_review_vectors(db, review)
            db.commit()
            db.refresh(review)
            return review
        except Exception:
            db.rollback()
            raise
    finally:
        if own_session:
            db.close()


def delete_review(review_id: int, db: Optional[Session] = None) -> bool:
    """删除 review 及其全部向量。"""
    own_session = db is None
    db = db or _session()
    try:
        review = db.get(Review, review_id)
        if review is None:
            return False
        _delete_review_vectors(db, review)
        db.delete(review)
        db.commit()
        return True
    finally:
        if own_session:
            db.close()


def list_reviews(item_id: int, db: Optional[Session] = None) -> List[Review]:
    """某 item 的全部 review，时间倒序。"""
    own_session = db is None
    db = db or _session()
    try:
        return db.query(Review).filter(Review.item_id == item_id) \
            .order_by(Review.created_at.desc()).all()
    finally:
        if own_session:
            db.close()


def get_my_rating(item_id: int, db: Optional[Session] = None) -> Optional[float]:
    """该 item 下全部 Review 评分的均值（忽略未打分的 Review）。

    - 只有一条 Review 时均值 = 该条评分（自然成立）；
    - 全部 Review 都未打分时返回 None（前端显示"暂无评分"而非 0）。
    """
    own_session = db is None
    db = db or _session()
    try:
        ratings = [
            r[0] for r in db.query(Review.rating)
            .filter(Review.item_id == item_id, Review.rating.isnot(None)).all()
        ]
    finally:
        if own_session:
            db.close()
    if not ratings:
        return None
    return round(sum(ratings) / len(ratings), 2)


def get_public_rating(item: Item) -> Optional[float]:
    """从外部收藏的 raw_metadata 提取大众评分（如 Bangumi 的 rating.score）。

    兼容两种结构：
    - 新结构（ADR 0016）：raw_metadata.detail.metadata.rating；
    - 旧结构：raw_metadata.rating（dict{score} 或数值）。
    """
    if item.source == "local" or not item.raw_metadata:
        return None
    meta = item.raw_metadata
    if not isinstance(meta, dict):
        return None
    detail = meta.get("detail")
    rating = None
    if isinstance(detail, dict) and isinstance(detail.get("metadata"), dict):
        rating = detail["metadata"].get("rating")
    if rating is None:
        rating = meta.get("rating")
    if isinstance(rating, dict):
        return rating.get("score")
    if isinstance(rating, (int, float)):
        return float(rating)
    return None
