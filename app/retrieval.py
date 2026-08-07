"""检索模块 - 向量检索 + tag 过滤 + 排序去重

设计取舍详见 docs/decisions/0002-retrieval-ranking-dedup.md。
"""
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import embeddings, vectorstore
from app.config import settings
from app.database import SessionLocal
from app.models import Item, Tag, item_tag_association
from app.schemas import RetrievedChunk


def _resolve_item_meta(
    db: Session, item_ids: List[int]
) -> Dict[int, tuple[str, List[str]]]:
    """批量拉取 item 的 title 和 tags，避免逐条 N+1 查询。"""
    if not item_ids:
        return {}
    items = db.query(Item).filter(Item.id.in_(item_ids)).all()
    return {it.id: (it.title, [t.name for t in it.tags]) for it in items}


def _select_item_ids_by_tags(db: Session, tags: List[str], match_all: bool = False) -> List[int]:
    """先用 SQL 筛选出符合条件的 item_id 列表。

    - match_all=False（any）：包含任意指定标签；
    - match_all=True（all）：必须同时包含全部指定标签。
    """
    rows = (
        db.query(Item.id)
        .join(item_tag_association, Item.id == item_tag_association.c.item_id)
        .join(Tag, Tag.id == item_tag_association.c.tag_id)
        .filter(Tag.name.in_(tags))
        .group_by(Item.id)
            .having(
                # having len(distinct matched tags) >= len(tags) 表示全命中
                func.count(func.distinct(Tag.id)) >= len(tags)
                if match_all
                else func.count(Tag.id) >= 1
            )
        .all()
    )
    return [r[0] for r in rows]


def _build_item_where(item_ids: List[int]) -> dict:
    """构造 Chroma where 过滤条件。

    注：chromadb 1.0.x 的 `{"$in": [...]}` 校验有 bug（会误报），
    改用 `$or` + 等值条件的等价写法，兼容性更好。
    """
    if len(item_ids) == 1:
        return {"item_id": item_ids[0]}
    return {"$or": [{"item_id": i} for i in item_ids]}


def _get_spoiler_review_ids(db: Session, review_ids: List[Optional[int]]) -> set:
    """批量查出 spoiler=1 的 review id（用于检索过滤，见 ADR 0017）。"""
    ids = [r for r in review_ids if r is not None]
    if not ids:
        return set()
    from app.models import Review
    rows = db.query(Review.id).filter(
        Review.id.in_(ids), Review.spoiler == 1
    ).all()
    return {r[0] for r in rows}


def retrieve_chunks(
    query: str,
    top_k: int = 5,
    tags: Optional[List[str]] = None,
    max_chunks_per_item: Optional[int] = None,
    tag_match: str = "any",
    db: Optional[Session] = None,
) -> List[RetrievedChunk]:
    """语义检索相关 chunk。

    - tags=None：全库向量检索；
    - tags 非空：先用 SQL 筛 item_ids，再作为 Chroma where 过滤条件；
      tag_match="any" 为任意命中，"all" 为全部命中（交集）；
    - 排序：按余弦相似度降序；
    - 去重：先去掉内容完全相同的 chunk，再按 item 去重（默认每 item 留 1 条，
      max_chunks_per_item 可调），最终截取 top_k 条。
    """
    own_session = db is None
    db = db or SessionLocal()
    try:
        return _retrieve(db, query, top_k, tags, max_chunks_per_item, tag_match)
    finally:
        if own_session:
            db.close()


def _retrieve(
    db: Session,
    query: str,
    top_k: int,
    tags: Optional[List[str]],
    max_chunks_per_item: Optional[int],
    tag_match: str = "any",
) -> List[RetrievedChunk]:
    if not query or not query.strip():
        return []
    if tags:
        item_ids = _select_item_ids_by_tags(db, tags, match_all=(tag_match == "all"))
        if not item_ids:
            return []
        where = _build_item_where(item_ids)
    else:
        where = None

    q_vector = embeddings.embed_query(query)  # 可能抛 EmbeddingError
    collection = vectorstore.get_collection()

    # 多取一些候选，给去重留足余地
    n_results = max(top_k * 4, 20)
    result = collection.query(
        query_embeddings=[q_vector],
        n_results=n_results,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    dists = (result.get("distances") or [[]])[0]

    hits: List[RetrievedChunk] = []
    for doc, meta, dist in zip(docs, metas, dists):
        if not doc or not meta:
            continue
        item_id = meta.get("item_id")
        if item_id is None:
            continue
        review_id = meta.get("review_id")
        hits.append(
            RetrievedChunk(
                content=doc,
                item_id=int(item_id),
                item_title="",  # 稍后批量填充
                score=round(1.0 - float(dist), 4),  # cosine distance -> similarity
                tags=[],
                source_type="review" if review_id is not None else "item",
                review_id=int(review_id) if review_id is not None else None,
            )
        )

    # 过滤 spoiler 剧透内容（Review spoiler=true 的 chunk 不参与检索，见 ADR 0017）
    spoilered = _get_spoiler_review_ids(db, [h.review_id for h in hits])
    if spoilered:
        hits = [h for h in hits if h.review_id not in spoilered]

    # 1) 内容去重
    seen_content = set()
    unique_hits = []
    for h in hits:
        if h.content not in seen_content:
            seen_content.add(h.content)
            unique_hits.append(h)

    # 2) 排序（余弦相似度降序）——Chroma 已按距离升序，这里显式保证
    unique_hits.sort(key=lambda h: h.score, reverse=True)

    # 3) 按 item 去重
    cap = max_chunks_per_item if max_chunks_per_item is not None else settings.max_chunks_per_item
    per_item: Dict[int, int] = {}
    deduped: List[RetrievedChunk] = []
    for h in unique_hits:
        if per_item.get(h.item_id, 0) < cap:
            per_item[h.item_id] = per_item.get(h.item_id, 0) + 1
            deduped.append(h)
        if len(deduped) >= top_k:
            break

    # 4) 填充标题与标签（含 review 标题）
    need = {h.item_id for h in deduped}
    meta_map = _resolve_item_meta(db, list(need))
    for h in deduped:
        title, tag_names = meta_map.get(h.item_id, ("", []))
        h.item_title = title
        h.tags = tag_names
        if h.review_id is not None:
            h.review_title = _resolve_review_title(db, h.review_id)

    return deduped


def _resolve_review_title(db: Session, review_id: int) -> Optional[str]:
    """拉取 review 标题（无标题时给占位提示，便于 prompt 标注来源）。"""
    from app.models import Review
    r = db.get(Review, review_id)
    if r is None:
        return None
    return r.title or "读后感"
