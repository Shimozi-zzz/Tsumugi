"""Collection 收藏关系模块（P2 / ADR 0046）

收藏状态（追番状态/收藏时间/是否喜欢）从 Review 分离到独立的 collections 表：
- 1:1 关联 items（外部作品），status=想看/在看/看完/搁置/弃坑；
- 收藏时刻自动生成最轻 Collection Memory（source_type=collection，source_ref=item_id）；
- 幂等回填：历史外部条目建 collection 行（status 从"从 Bangumi 导入"Review 迁移，
  added_at=item.created_at，favorite=0）；**不为历史条目批量造收藏 Memory**（避免污染
  记忆回廊，收藏时刻 Memory 只对"新增收藏"生效）。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Collection, Item, Memory

COLLECTION_STATUSES = ["想看", "在看", "看完", "搁置", "弃坑"]


def ensure_collection(item: Item, db: Session) -> Collection:
    """确保该作品有 collection 行（1:1）。返回该行；新建时写入 added_at。"""
    col = db.get(Collection, item.id)
    if col is None:
        col = Collection(item_id=item.id, added_at=item.created_at or datetime.now(), favorite=0)
        db.add(col)
        db.flush()
    return col


def set_collection(
    item_id: int,
    db: Session,
    status: Optional[str] = None,
    favorite: Optional[int] = None,
) -> Collection:
    """更新收藏状态/是否喜欢（status 需在枚举内；None 表示不变，空串表示清除）。

    Phase D（ADR 0062）：状态**迁移到"看完"**时自动生成 milestone Memory——
    真实完成事件（未看完 → 看完）才会触发，同一次"看完"重复保存幂等（不重复）；
    看完 → 其他 → 再次看完视为新的完成事件，可再生成。
    """
    item = db.get(Item, item_id)
    if item is None:
        raise ValueError(f"item {item_id} 不存在")
    col = ensure_collection(item, db)
    if status is not None:
        s = status.strip() if isinstance(status, str) else status
        if s and s not in COLLECTION_STATUSES:
            raise ValueError(f"status 必须是 {COLLECTION_STATUSES} 之一")
        old_status = col.status
        col.status = s or None
        if s == "看完" and old_status != "看完":
            create_completion_memory(item, db)
    if favorite is not None:
        col.favorite = 1 if favorite else 0
    db.commit()
    db.refresh(col)
    return col


def create_completion_memory(item: Item, db: Session) -> Memory:
    """完成时刻 → milestone Memory（"这一天，我把《{title}》看完了"）。

    Phase D（ADR 0062）：用户把作品状态改为"看完"时自动生成，无需写任何文字。
    - 与收藏时刻（collection Memory）同款轻量模式：**不写向量**——完成时刻
      不被可选 embedding 阻塞（Core 无 AI 也完整）；若需参与个人语义检索，
      由启动时 backfill_memory_vectors 幂等补向量（source_type=memory，ADR 0051）；
    - source_ref=NULL（无主记录，同 text/milestone 直接记忆）；
    - 允许被删除（delete_direct_memory 允许 milestone 类型）。
    """
    mem = Memory(
        item_id=item.id,
        source_type="milestone",
        source_ref=None,
        occurred_at=datetime.now(),
        summary=f"这一天，我把《{item.title}》看完了",
    )
    db.add(mem)
    db.flush()
    return mem


def ensure_collection_memory(item: Item, db: Session) -> Memory:
    """收藏时刻 → 最轻 Collection Memory（"这一天，我把它带回了图书馆"）。幂等。"""
    mem = db.query(Memory).filter(
        Memory.source_type == "collection", Memory.source_ref == item.id,
    ).first()
    if mem is None:
        mem = Memory(
            item_id=item.id,
            source_type="collection",
            source_ref=item.id,
            occurred_at=datetime.now(),
            summary="这一天，我把它带回了图书馆",
        )
        db.add(mem)
        db.flush()
    return mem


def on_collect(item: Item, db: Session) -> bool:
    """收藏入库时的收藏关系维护：确保 collection 行；**首次收藏**生成收藏时刻 Memory。

    返回是否为新收藏（调用方据此决定是否提示"已收藏"语义）。
    """
    is_new = db.get(Collection, item.id) is None
    ensure_collection(item, db)
    if is_new:
        ensure_collection_memory(item, db)
    return is_new


def backfill_collections(engine) -> int:
    """历史外部条目幂等回填 collection 行（1:1）。返回新建条数。"""
    from sqlalchemy.orm import Session

    with Session(engine) as db:
        n = 0
        for item in db.query(Item).filter(Item.source != "local").all():
            if db.get(Collection, item.id) is not None:
                continue
            # status 从"从 Bangumi 导入"Review 迁移（保留书评，不删除）
            status = None
            for r in item.reviews:
                if r.source == "bangumi_collection" and r.status:
                    status = r.status
                    break
            db.add(Collection(item_id=item.id, status=status,
                              added_at=item.created_at, favorite=0))
            n += 1
        if n:
            db.commit()
        return n
