"""Character 角色实体（P4 / ADR 0048）：从 raw_metadata 提炼为表，跨作品聚合。

- 去重键：(source, external_id) 优先，缺 id 时 (source, name)；
- relation 合并（主角优先）；actors 存 JSON 数组（声优名）；
- sync_characters 重建单作品角色索引（清旧链接 → upsert → 建链接，删孤儿）；
- backfill_characters 启动时全量幂等重建；
- raw_metadata 保留为权威来源，表是派生索引（收藏/刷新时同步）。
"""
import json
from typing import List

from sqlalchemy.orm import Session

from app.models import Character, Item


def extract_characters(item: Item) -> List[dict]:
    """从条目 raw_metadata 提取角色列表（统一结构，见 ADR 0016/0048）。"""
    raw = item.raw_metadata
    if not isinstance(raw, dict):
        return []
    detail = raw.get("detail")
    if not isinstance(detail, dict):
        return []
    meta = detail.get("metadata")
    if not isinstance(meta, dict):
        return []
    chars = meta.get("characters")
    if isinstance(chars, list):
        return [c for c in chars if isinstance(c, dict)]
    return []


def _find_character(db: Session, source: str, c: dict):
    eid = c.get("id")
    if eid:
        return db.query(Character).filter(
            Character.source == source, Character.external_id == str(eid)
        ).first()
    name = c.get("name")
    if not name:
        return None
    return db.query(Character).filter(
        Character.source == source, Character.name == str(name)
    ).first()


def _actors_json(actors) -> str:
    if not actors:
        return None
    return json.dumps(actors, ensure_ascii=False)


def sync_characters(item: Item, db: Session) -> None:
    """重建该作品的角色索引：清旧链接 → upsert 角色 → 建链接；孤儿角色删除。"""
    # 1) 断开旧链接（association 行删除）
    for ch in list(item.characters):
        item.characters.remove(ch)
    db.flush()

    # 2) 提取并 upsert
    for c in extract_characters(item):
        name = c.get("name")
        if not name:
            continue
        ch = _find_character(db, item.source, c)
        if ch is None:
            ch = Character(
                source=item.source,
                external_id=str(c["id"]) if c.get("id") else None,
                name=str(name),
            )
            db.add(ch)
            db.flush()
        if str(name) != ch.name:
            ch.name = str(name)
        rel = c.get("relation")
        if rel and (ch.relation is None or (ch.relation != "主角" and rel == "主角")):
            ch.relation = rel
        if c.get("image_url") and not ch.image_url:
            ch.image_url = c["image_url"]
        if c.get("summary") and not ch.summary:
            ch.summary = c["summary"]
        if c.get("actors"):
            ch.actors = _actors_json(c["actors"])
        if ch not in item.characters:
            item.characters.append(ch)
    db.flush()

    # 3) 删孤儿角色（无任何作品链接）
    for orphan in db.query(Character).filter(~Character.works.any()).all():
        db.delete(orphan)
    db.flush()


def backfill_characters(engine) -> int:
    """全量幂等重建角色索引（启动时调用）。返回角色总数。"""
    from sqlalchemy.orm import Session

    with Session(engine) as db:
        for item in db.query(Item).filter(Item.source != "local").all():
            sync_characters(item, db)
        db.commit()
        return db.query(Character).count()
