"""Memory 记忆核心模块（Phase A，ADR 0041）

Memory 是独立容器：收纳"图书馆里发生过的、值得被记住的时刻"。本轮只实现
`review` 这一种素材来源（用户通过 reviews.create_review 创建 Review 时自动
同步 Memory 行；编辑/删除 Review 时同步/删除对应 Memory，不留孤儿记录）。

设计要点（详见 docs/decisions/0041-memory-core.md）：
- **Memory 不参与独立 RAG**：v1.1 明确"Memory 是语义容器，RAG 检索其中的
  素材"——本轮不为 Memory 表设计 embedding/chunk，底层 Review 依然按现有
  source_type=review 机制正常参与检索；
- **source_ref 是多态引用**（review 时 = Review.id），不设外键，为未来
  text/image/collection/milestone 等来源预留；
- **summary 是冗余展示字段**：Review 内容可能很长，列表/时间轴展示时逐条
  实时关联查询不划算，存一份简短摘要（标题优先，否则截断内容首行）。
"""
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import Integer, cast, func
from sqlalchemy.orm import Session

from app import embeddings, vectorstore
from app.ingest import split_text
from app.models import Chunk, Item, Memory, Review

MEMORY_SOURCE_REVIEW = "review"
# P3（ADR 0047）：可直接创建的轻量 Memory 来源类型（不经过书评系统）
DIRECT_MEMORY_TYPES = ["text", "milestone"]


def _session():
    # 函数体内 import：与 reviews._session 同套路，测试 patch 时能覆盖
    from app.database import SessionLocal
    return SessionLocal()

_SUMMARY_LIMIT = 40


def _review_summary(review: Review) -> str:
    """从 Review 生成简短摘要：优先标题，否则截断内容（折叠换行为空格）。"""
    text = (review.title or "").strip()
    if text:
        return text
    content = (review.content or "").replace("\n", " ").strip()
    return content[:_SUMMARY_LIMIT] + ("…" if len(content) > _SUMMARY_LIMIT else "")


def ensure_review_memory(review: Review, db: Session) -> Memory:
    """Review 创建/发布时生成 Memory 条目（幂等：同 source_ref 已存在则更新）。

    与 Review 同事务提交：Review 插入失败时 Memory 一并回滚。
    """
    mem = db.query(Memory).filter(
        Memory.source_type == MEMORY_SOURCE_REVIEW,
        Memory.source_ref == review.id,
    ).first()
    if mem is None:
        mem = Memory(
            item_id=review.item_id,
            source_type=MEMORY_SOURCE_REVIEW,
            source_ref=review.id,
            occurred_at=review.created_at or datetime.now(),
            summary=_review_summary(review),
        )
        db.add(mem)
    else:
        mem.item_id = review.item_id
        mem.summary = _review_summary(review)
    return mem


def sync_review_memory(review: Review, db: Session) -> Optional[Memory]:
    """Review 编辑时同步 Memory 摘要（只更新已存在的记录；不存在的跳过——
    兼容 Bangumi 导入等不走 create_review 的路径，不为其凭空造 Memory）。"""
    mem = db.query(Memory).filter(
        Memory.source_type == MEMORY_SOURCE_REVIEW,
        Memory.source_ref == review.id,
    ).first()
    if mem is None:
        return None
    mem.item_id = review.item_id
    mem.summary = _review_summary(review)
    return mem


def delete_review_memory(review_id: int, db: Session) -> int:
    """删除某条 review 对应的 Memory 行（不留孤儿记录）。返回删除条数。"""
    deleted = db.query(Memory).filter(
        Memory.source_type == MEMORY_SOURCE_REVIEW,
        Memory.source_ref == review_id,
    ).delete()
    return deleted or 0


def _memory_chunk_ids(mem: Memory, n: int) -> List[str]:
    return [f"memory{mem.id}_chunk{i}" for i in range(n)]


def _write_memory_vectors(db: Session, mem: Memory) -> None:
    """把直接 Memory（text/milestone）的 summary 切分 → embedding → Chroma + Chunk 行。

    P7（ADR 0051）：Memory 内容以 source_type=memory 参与个人语义检索
    （"我以前写过哪些关于…"能找到轻量记忆）。与 review 向量同一模式。
    """
    chunks = split_text(mem.summary or "")
    if not chunks:
        return
    vectors = embeddings.embed_texts(chunks)  # 可能抛 EmbeddingError
    ids = _memory_chunk_ids(mem, len(chunks))
    metadatas = [
        {
            "item_id": mem.item_id, "memory_id": mem.id, "chunk_index": i,
            "source_type": "memory",
        }
        for i in range(len(chunks))
    ]
    vectorstore.get_collection().add(
        ids=ids, embeddings=vectors, documents=chunks, metadatas=metadatas,
    )
    for i, (content, ref) in enumerate(zip(chunks, ids)):
        db.add(Chunk(
            item_id=mem.item_id, memory_id=mem.id,
            content=content, chunk_index=i, embedding_ref=ref,
            source_type="memory",
        ))


def _delete_memory_vectors(db: Session, mem: Memory) -> None:
    """删除直接 Memory 的全部向量与 Chunk 行（删除记忆时调用）。"""
    refs = [c.embedding_ref for c in db.query(Chunk)
            .filter(Chunk.memory_id == mem.id).all() if c.embedding_ref]
    if refs:
        try:
            vectorstore.get_collection().delete(ids=refs)
        except Exception:
            pass
    db.query(Chunk).filter(Chunk.memory_id == mem.id).delete()


def create_direct_memory(
    item_id: int,
    summary: str,
    source_type: str,
    emotion: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
    db: Session = None,
) -> Memory:
    """创建一条直接创建的 Memory（P3 / ADR 0047）：轻量文字/里程碑，不经过书评。

    - source_type ∈ DIRECT_MEMORY_TYPES（text / milestone）；summary 即正文；
    - emotion 可选（固定小集由前端 chips 提供，后端不强制枚举）；
    - occurred_at 默认现在；
    - P7（ADR 0051）：summary 切分写入向量（source_type=memory）参与个人语义检索。
    """
    if source_type not in DIRECT_MEMORY_TYPES:
        raise ValueError(f"source_type 必须是 {DIRECT_MEMORY_TYPES} 之一")
    if not summary or not summary.strip():
        raise ValueError("轻量记录不能为空")
    item = db.get(Item, item_id)
    if item is None:
        raise ValueError(f"item {item_id} 不存在")
    mem = Memory(
        item_id=item_id,
        source_type=source_type,
        source_ref=None,
        occurred_at=occurred_at or datetime.now(),
        summary=summary.strip(),
        emotion=emotion or None,
    )
    db.add(mem)
    db.flush()  # 拿到 id
    try:
        _write_memory_vectors(db, mem)
        db.commit()
        db.refresh(mem)
        return mem
    except Exception:
        db.rollback()
        if mem.id:
            try:
                refs = [c.embedding_ref for c in db.query(Chunk)
                        .filter(Chunk.memory_id == mem.id).all() if c.embedding_ref]
                if refs:
                    vectorstore.get_collection().delete(ids=refs)
            except Exception:
                pass
        raise


def delete_direct_memory(memory_id: int, db: Session = None) -> bool:
    """删除直接创建的 Memory（text/milestone，含其媒体附件与向量级联）。"""
    own_session = db is None
    db = db or _session()
    try:
        mem = db.get(Memory, memory_id)
        if mem is None:
            return False
        if mem.source_type not in DIRECT_MEMORY_TYPES:
            return False  # review/collection 记忆由各自系统管理，不允许这里删
        _delete_memory_vectors(db, mem)
        db.delete(mem)
        db.commit()
        return True
    finally:
        if own_session:
            db.close()


def backfill_memory_vectors(engine) -> int:
    """为缺向量的直接 Memory 幂等补向量（启动时调用；历史 text/milestone 记忆）。"""
    from sqlalchemy.orm import Session

    with Session(engine) as db:
        n = 0
        for mem in db.query(Memory).filter(Memory.source_type.in_(DIRECT_MEMORY_TYPES)).all():
            has = db.query(Chunk.id).filter(Chunk.memory_id == mem.id).first() is not None
            if not has:
                _write_memory_vectors(db, mem)
                n += 1
        if n:
            db.commit()
        return n


def list_item_memories(item_id: int, db: Session) -> List[Memory]:
    """某作品的全部 Memory，按发生时间倒序（最新在前）。Phase B 作品时间轴用。"""
    return db.query(Memory).filter(Memory.item_id == item_id) \
        .order_by(Memory.occurred_at.desc(), Memory.id.desc()).all()


def query_on_this_day(
    db: Session,
    month: int,
    day: int,
    max_year: Optional[int] = None,
    limit: int = 20,
) -> List[Memory]:
    """跨年同月同日查询（Phase E 往年今日）：历史上任意年份、月-日与目标相同的 Memory。

    - 只匹配**严格同月同日**：2 月 29 日的记忆只在 2 月 29 日当天被命中
      （闰年才有），2 月 28 日不"前移/后移"匹配——避免"前天/昨天"式的模糊
      （见 ADR 0044 闰年边界说明）；
    - max_year 通常传当前年份，过滤掉今年（往年今日 = year < 今年）；
    - 排序：年份倒序（最近的年份在前），同一天内 occurred_at 倒序——
      前端取首条即"最近的年份、该日最新一条"，作为选取规则（ADR 0044）。
    """
    mm = f"{int(month):02d}"
    dd = f"{int(day):02d}"
    q = db.query(Memory).filter(func.strftime("%m-%d", Memory.occurred_at) == f"{mm}-{dd}")
    if max_year is not None:
        # strftime 返回 TEXT，与整数比较永远 false（SQLite 排序：数字 < 文本）；
        # 必须 CAST 成 INTEGER（substr 同理）。
        q = q.filter(cast(func.strftime("%Y", Memory.occurred_at), Integer) < max_year)
    return q.order_by(Memory.occurred_at.desc(), Memory.id.desc()).limit(limit).all()


def backfill_reviews(engine) -> int:
    """给存量 Review 补生成 Memory 行（幂等：只为没有对应 Memory 的 Review 建）。

    理由（ADR 0041/0042）：Phase B 时间轴要让**旧书评也能出现**——"这部作品在
    我这里留下了什么"，而不是只对新书评生效。启动时调用，O(n) 次查询级别，
    个人库体量下开销可忽略；多次运行只补缺口，不重复。
    """
    from sqlalchemy.orm import Session
    from app.models import Review

    with Session(engine) as db:
        existing = {ref for (ref,) in db.query(Memory.source_ref)
                    .filter(Memory.source_type == MEMORY_SOURCE_REVIEW).all()}
        rows = []
        for r in db.query(Review).all():
            if r.id not in existing:
                rows.append(Memory(
                    item_id=r.item_id,
                    source_type=MEMORY_SOURCE_REVIEW,
                    source_ref=r.id,
                    occurred_at=r.created_at or datetime.now(),
                    summary=_review_summary(r),
                ))
        if rows:
            db.add_all(rows)
            db.commit()
        return len(rows)


def _parse_dt(s: str) -> datetime:
    """解析 ISO 时间；纯日期（YYYY-MM-DD）视为当日 00:00:00；年份（YYYY）视为 1 月 1 日。"""
    s = s.strip()
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    if len(s) == 4 and s.isdigit():  # 年份
        return datetime(int(s), 1, 1)
    try:
        return datetime.fromisoformat(s + "T00:00:00")
    except ValueError:
        raise ValueError(f"无法解析的时间：{s}")


def query_memories(
    db: Session,
    item_id: Optional[int] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[Memory]:
    """全局查询 Memory（Phase C 记忆回廊 / P6 检索台）：按时间范围 / item / 文本筛选。

    start/end 支持 ISO 时间、纯日期或年份；纯日期作 end 时按当日结束
    （exclusive）处理，年份作 end 时按次年 1 月 1 日处理——便于"按
    2023/2024/2025 年份"这类筛选。search 按 summary 子串匹配。
    """
    q = db.query(Memory)
    if item_id is not None:
        q = q.filter(Memory.item_id == item_id)
    if start:
        q = q.filter(Memory.occurred_at >= _parse_dt(start))
    if end:
        e = end.strip()
        if len(e) == 4 and e.isdigit():  # 年份 → 次年 1 月 1 日（exclusive）
            end_dt = datetime(int(e) + 1, 1, 1)
        elif len(e) <= 10:  # 纯日期 → 当日结束（不含次日）
            end_dt = _parse_dt(e) + timedelta(days=1)
        else:
            end_dt = _parse_dt(e)
        q = q.filter(Memory.occurred_at < end_dt)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(Memory.summary.ilike(like))
    return q.order_by(Memory.occurred_at.desc(), Memory.id.desc()) \
        .offset(skip).limit(limit).all()
