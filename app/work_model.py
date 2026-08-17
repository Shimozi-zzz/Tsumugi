"""Work 模型世界轴列（P1 / ADR 0045）

从统一 raw_metadata（ADR 0016 结构：detail.metadata）幂等提炼可查询的世界轴列：
work_type / alternative_title / release_date。规则：
- 只填 NULL，**不覆盖用户已填值**（个人数据优先）；
- 幂等：重复运行只补缺口（与 backfill_reviews 同套路）；
- creator / series_name 等推迟到 P4 实体表（Character/Series/Creator），本阶段不落列。
"""
from typing import Dict

from app.models import Item

# bangumi subject type → work_type（2=动画 4=游戏 1=漫画/书籍 3=音乐 6=三次元；
# 1 同时含轻小说，映射为 manga 并允许用户手动改）
_BANGUMI_TYPE_TO_WORK: Dict[int, str] = {1: "manga", 2: "anime", 3: "other", 4: "game", 6: "other"}

WORK_TYPES = ["anime", "manga", "game", "galgame", "novel", "other"]


def extract_work_columns(raw_metadata) -> Dict[str, str]:
    """从 raw_metadata 提炼世界轴列，只返回确定非空的字段。"""
    out: Dict[str, str] = {}
    if not isinstance(raw_metadata, dict):
        return out
    detail = raw_metadata.get("detail")
    md = detail.get("metadata") if isinstance(detail, dict) else None
    if not isinstance(md, dict):
        return out
    wt = md.get("type")
    if isinstance(wt, int) and wt in _BANGUMI_TYPE_TO_WORK:
        out["work_type"] = _BANGUMI_TYPE_TO_WORK[wt]
    elif isinstance(wt, str) and wt.lower() in WORK_TYPES:
        # Phase 11-A：非 Bangumi 数据源（如 AniList）直接给 work_type 字符串
        out["work_type"] = wt.lower()
    alt = md.get("original_name")
    if isinstance(alt, str) and alt.strip():
        out["alternative_title"] = alt.strip()
    date = md.get("date")
    if isinstance(date, str) and date.strip():
        out["release_date"] = date.strip()
    return out


def apply_work_columns(item: Item, raw_metadata) -> None:
    """收藏入库时直接提炼写入世界轴列（只填 NULL，不覆盖用户已填）。"""
    for k, v in extract_work_columns(raw_metadata).items():
        if getattr(item, k) is None:
            setattr(item, k, v)


def backfill_work_columns(engine) -> int:
    """历史外部条目幂等回填世界轴列（只填 NULL）。返回发生变更的条数。"""
    from sqlalchemy.orm import Session

    with Session(engine) as db:
        n = 0
        for item in db.query(Item).filter(Item.source != "local").all():
            cols = extract_work_columns(item.raw_metadata)
            changed = False
            for k, v in cols.items():
                if getattr(item, k) is None:
                    setattr(item, k, v)
                    changed = True
            if changed:
                n += 1
        if n:
            db.commit()
        return n
