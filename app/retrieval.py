"""检索模块 - 向量检索 + tag 过滤 + 排序去重 + 来源区分（ADR 0025）

设计取舍详见 docs/decisions/0002-retrieval-ranking-dedup.md 与
docs/decisions/0025-external-reference-rag.md。

来源区分策略：
- 每个 chunk 的 source_type 由 SQLite 权威解析（Chunk.source_type/connector），
  Chroma metadata 里的 source_type 仅作快速路径（新写向量都带）；
- 默认问答：note/review（用户自己写的内容）权重 1.0，external_reference
  （外部百科资料）权重 = settings.external_reference_weight（默认 0.4），
  保证主观问题优先命中用户自己的内容，外部百科只作事实性补充；
- 支持按 source_types 硬过滤（如只看用户自己的内容）。
"""
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import embeddings, vectorstore
from app.config import settings
from app.database import SessionLocal
from app.models import Chunk, Item, Tag, item_tag_association
from app.schemas import RetrievedChunk


# ---------------------------------------------------------------- 轻量意图识别（Phase 10-1-B-3）
# 确定性关键词规则，不引入 LLM。仅用于选择检索策略（来源优先 / 候选池），不改数据/权重/排序。

_PERSONAL_TERMS = ("我的", "我喜欢", "我想", "我和", "我的经历", "回忆", "记得", "记录", "留下", "评价", "感想", "看完", "看过", "看了", "喜欢")
_TEMPORAL_TERMS = ("去年", "以前", "今年", "最近", "那时候", "当时", "前年", "之前", "上个月", "上周", "昨天")
_RECOMMEND_TERMS = ("推荐", "想重温", "想看", "类似", "哪些作品", "什么作品", "值得")


class QueryIntent:
    def __init__(self, personal=False, temporal=False, recommendation=False):
        self.personal = personal
        self.temporal = temporal
        self.recommendation = recommendation


def detect_query_intent(query: str) -> QueryIntent:
    """确定性关键词意图识别（不引入 LLM 分类）。"""
    q = query or ""
    return QueryIntent(
        personal=any(t in q for t in _PERSONAL_TERMS),
        temporal=any(t in q for t in _TEMPORAL_TERMS),
        recommendation=any(t in q for t in _RECOMMEND_TERMS),
    )


# ---------------------------------------------------------------- 时间信号（Phase 10-1-B-6）
# 时间型个人问题使用 occurred_at metadata 做时间命中调整（非文本关键词判断）。
# 原则：只对明确时间边界生效；unknown/缺失不报错、不加不减、不伪装命中；external 不加分。
# 时间窗口与 boost 数值均为保守、可解释的固定值（additive，避免 multiplicative 失真）。

TEMPORAL_BONUS = 0.15   # 明确时间范围内命中的个人 chunk 加分
TEMPORAL_PENALTY = 0.05  # 明确位于范围外的个人 chunk 减分
RECENT_WINDOW_DAYS = 30  # 「最近」固定窗口（项目无既有定义，采用 30 天）


def _current_time() -> datetime:
    """可注入的当前时间（production 用系统时间；tests monkeypatch 固定，避免随机器日期漂移）。"""
    return datetime.now()


def _explicit_temporal_range(query: str, now: datetime) -> Optional[tuple]:
    """由查询中的明确时间词计算 [start, end]（naive datetime 闭区间）。

    模糊词（以前/之前/那时候/当时）无明确边界 → None（不虚构、不硬过滤）。
    """
    q = query or ""
    y = now.year
    if "前年" in q:
        return (datetime(y - 2, 1, 1), datetime(y - 2, 12, 31, 23, 59, 59))
    if "去年" in q:
        return (datetime(y - 1, 1, 1), datetime(y - 1, 12, 31, 23, 59, 59))
    if "今年" in q:
        return (datetime(y, 1, 1), datetime(y, 12, 31, 23, 59, 59))
    if "上个月" in q:
        first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_prev = first_this - timedelta(days=1)
        return (end_prev.replace(day=1), end_prev.replace(hour=23, minute=59, second=59))
    if "上周" in q:
        this_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        prev_monday = this_monday - timedelta(days=7)
        return (prev_monday, prev_monday + timedelta(days=6, hours=23, minutes=59, seconds=59))
    if "昨天" in q:
        d = (now - timedelta(days=1)).date()
        return (datetime(d.year, d.month, d.day), datetime(d.year, d.month, d.day, 23, 59, 59))
    if "最近" in q:
        d = now.date()
        return (datetime(d.year, d.month, d.day) - timedelta(days=RECENT_WINDOW_DAYS),
                datetime(d.year, d.month, d.day, 23, 59, 59))
    return None


def _parse_occurred_at(value) -> Optional[datetime]:
    """解析 B-5 写入的 ISO-8601 occurred_at（date/datetime、可含时区）。None/非法/缺失 → None。"""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        try:
            d = date.fromisoformat(str(value))
            parsed = datetime(d.year, d.month, d.day)
        except ValueError:
            return None
    return parsed.replace(tzinfo=None)  # 统一 naive 墙钟比较（SQLite 存 naive，墙钟即项目惯例）


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


def _resolve_chunk_sources(db: Session, refs: List[Optional[str]]) -> Dict[str, tuple]:
    """embedding_ref -> (source_type, connector)，批量查询（DB 为权威）。

    返回缺失项不在 map 中；调用方按需回退（review_id 推导 / 默认 note）。
    """
    refs = [r for r in refs if r]
    if not refs:
        return {}
    rows = db.query(Chunk.embedding_ref, Chunk.source_type, Chunk.connector).filter(
        Chunk.embedding_ref.in_(refs)
    ).all()
    return {r[0]: (r[1], r[2]) for r in rows if r[0]}


def _source_weight(source_type: Optional[str]) -> float:
    """按来源类型给相似度加权（ADR 0025）。用户内容=1.0，外部百科=系数。"""
    if source_type == "external_reference":
        return getattr(settings, "external_reference_weight", 0.4)
    return 1.0


def retrieve_chunks(
    query: str,
    top_k: int = 5,
    tags: Optional[List[str]] = None,
    max_chunks_per_item: Optional[int] = None,
    tag_match: str = "any",
    source_types: Optional[List[str]] = None,
    db: Optional[Session] = None,
) -> List[RetrievedChunk]:
    """语义检索相关 chunk。

    - tags=None：全库向量检索；
    - tags 非空：先用 SQL 筛 item_ids，再作为 Chroma where 过滤条件；
      tag_match="any" 为任意命中，"all" 为全部命中（交集）；
    - source_types 非空：只返回来源类型在给定集合内的 chunk（硬过滤）；
    - 排序：按"相似度 × 来源权重"降序（external_reference 默认压低）；
    - 去重：先去掉内容完全相同的 chunk，再按 item 去重（默认每 item 留 1 条，
      max_chunks_per_item 可调），最终截取 top_k 条。
    """
    own_session = db is None
    db = db or SessionLocal()
    try:
        return _retrieve(
            db, query, top_k, tags, max_chunks_per_item, tag_match, source_types
        )
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
    source_types: Optional[List[str]] = None,
    candidate_pool: Optional[int] = None,
) -> List[RetrievedChunk]:
    if not query or not query.strip():
        return []
    # Phase 10-1-B-3：轻量意图 → 检索策略
    # - personal/temporal：个人来源优先（external 兜底补位），避免百科抢占个人问题
    # - recommendation/temporal：扩大候选池，提升多作品覆盖
    intent = detect_query_intent(query)
    prefer_personal = source_types is None and (intent.personal or intent.temporal)
    n_results = candidate_pool or max(top_k * 6, 40)
    if intent.recommendation or intent.temporal:
        n_results = max(n_results, 80)
    if tags:
        item_ids = _select_item_ids_by_tags(db, tags, match_all=(tag_match == "all"))
        if not item_ids:
            return []
        where = _build_item_where(item_ids)
    else:
        where = None

    q_vector = embeddings.embed_query(query)  # 可能抛 EmbeddingError
    collection = vectorstore.get_collection()

    result = collection.query(
        query_embeddings=[q_vector],
        n_results=n_results,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    ids = (result.get("ids") or [[]])[0]
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    dists = (result.get("distances") or [[]])[0]

    # DB 权威解析来源（对没有 source_type metadata 的历史向量走兜底）
    source_map = _resolve_chunk_sources(db, list(ids))

    hits: List[RetrievedChunk] = []
    occ_by_content: Dict[str, str] = {}  # content -> occurred_at（B-5 新 metadata；旧向量无键）
    for ref, doc, meta, dist in zip(ids, docs, metas, dists):
        if not doc or not meta:
            continue
        item_id = meta.get("item_id")
        if item_id is None:
            continue
        review_id = meta.get("review_id")
        source_type = meta.get("source_type")
        connector = meta.get("connector")
        if source_type is None:
            db_st, db_conn = source_map.get(ref, (None, None))
            source_type = db_st or ("review" if review_id is not None else "note")
            connector = connector or db_conn
        if meta.get("occurred_at"):
            occ_by_content[doc] = meta["occurred_at"]
        hits.append(
            RetrievedChunk(
                content=doc,
                item_id=int(item_id),
                item_title="",  # 稍后批量填充
                score=round(1.0 - float(dist), 4),  # cosine distance -> similarity
                tags=[],
                source_type=source_type or "note",
                review_id=int(review_id) if review_id is not None else None,
                connector=connector,
            )
        )

    # 过滤 spoiler 剧透内容（Review spoiler=true 的 chunk 不参与检索，见 ADR 0017）
    spoilered = _get_spoiler_review_ids(db, [h.review_id for h in hits])
    if spoilered:
        hits = [h for h in hits if h.review_id not in spoilered]

    # 按来源类型过滤（ADR 0025）
    # - 显式 source_types：硬过滤（保持原行为）
    # - 个人/时间意图（未显式指定）：个人来源优先；个人内容不足时外部百科兜底补位
    if prefer_personal:
        personal = [h for h in hits if h.source_type in ("memory", "review", "note")]
        external = [h for h in hits if h.source_type == "external_reference"]
        hits = personal if len(personal) >= top_k else personal + external
    elif source_types:
        allowed = set(source_types)
        hits = [h for h in hits if h.source_type in allowed]

    # Phase 10-1-B-6：temporal intent + 明确时间范围 → occurred_at 时间信号调整（仅个人来源，
    # 在内容去重 / per-item cap 之前生效；unknown 不加不减；external 不加分）
    if intent.temporal:
        trange = _explicit_temporal_range(query, _current_time())
        if trange is not None:
            start, end = trange
            for h in hits:
                if h.source_type not in ("memory", "review", "note"):
                    continue
                occ = _parse_occurred_at(occ_by_content.get(h.content))
                if occ is None:
                    continue  # 历史向量缺 occurred_at：视为 unknown，不伪装时间命中
                if start <= occ <= end:
                    h.score = round(h.score + TEMPORAL_BONUS, 4)
                else:
                    h.score = round(max(h.score - TEMPORAL_PENALTY, 0.0), 4)

    # 1) 内容去重
    seen_content = set()
    unique_hits = []
    for h in hits:
        if h.content not in seen_content:
            seen_content.add(h.content)
            unique_hits.append(h)

    # 2) 来源加权 + 排序（相似度 × 权重 降序）
    for h in unique_hits:
        h.score = round(h.score * _source_weight(h.source_type), 4)
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
