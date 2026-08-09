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

from sqlalchemy.orm import Session

from app.models import Item, Memory, Review

MEMORY_SOURCE_REVIEW = "review"

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


def list_item_memories(item_id: int, db: Session) -> List[Memory]:
    """某作品的全部 Memory，按发生时间倒序（最新在前）。Phase B 作品时间轴用。"""
    return db.query(Memory).filter(Memory.item_id == item_id) \
        .order_by(Memory.occurred_at.desc(), Memory.id.desc()).all()


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
    skip: int = 0,
    limit: int = 50,
) -> List[Memory]:
    """全局查询 Memory（Phase C 记忆回廊用）：按时间范围 / item 筛选。

    start/end 支持 ISO 时间、纯日期或年份；纯日期作 end 时按当日结束
    （exclusive）处理，年份作 end 时按次年 1 月 1 日处理——便于"按
    2023/2024/2025 年份"这类筛选。
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
    return q.order_by(Memory.occurred_at.desc(), Memory.id.desc()) \
        .offset(skip).limit(limit).all()
