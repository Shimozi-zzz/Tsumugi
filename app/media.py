"""统一作品实体 MediaEntry / MediaSource（Phase 11-B）

- Item 仍是持久化入口（Collection/Review/Memory/RAG 依赖 Item.id）；
- MediaEntry = 跨来源聚合层（item.media_id 可空，旧 Item 不受影响）；
- MediaSource = 每个 Item 在某 Provider 的来源身份（source+external_id 唯一）；
- 合并保守：规范化标题交集 + 类型族兼容 + 年份 ±1，宁留两条不误并；
- 字段级 fallback：title/description/image/rating/genres/status/episodes/staff/relations
  每个字段取最可靠的来源数据；raw_metadata 永不覆盖（保留各来源原始数据）。
"""
import json
import re
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import Item, MediaEntry, MediaRelation, MediaSource, Staff


def _norm_title(t) -> str:
    if not t:
        return ""
    s = str(t).lower().strip()
    return re.sub(r"[：:（）()\[\]【】「」『』《》\-—_·、，。.,\s]", "", s)


def _item_titles(item: Item) -> set:
    ts = {_norm_title(item.title)}
    if item.alternative_title:
        ts.add(_norm_title(item.alternative_title))
    ts.discard("")
    return ts


def item_year(item: Item) -> Optional[int]:
    rd = (item.release_date or "").strip()
    if rd and rd[:4].isdigit():
        return int(rd[:4])
    md = _meta(item, "date")
    if isinstance(md, str) and md[:4].isdigit():
        return int(md[:4])
    return None


def _meta(item: Item, key, default=None):
    raw = item.raw_metadata if isinstance(item.raw_metadata, dict) else None
    detail = raw.get("detail") if isinstance(raw, dict) else None
    md = detail.get("metadata") if isinstance(detail, dict) else None
    if not isinstance(md, dict):
        return default
    return md.get(key, default)


def _meta_list(item: Item, key: str) -> list:
    v = _meta(item, key)
    return v if isinstance(v, list) else []


def _mergeable(ta: Optional[str], tb: Optional[str], ya: Optional[int], yb: Optional[int]) -> bool:
    """保守合并判定：类型族不同 / 年份差 >1 → 不合并。"""
    if ta and tb and ta.lower() != tb.lower():
        return False
    if ya is not None and yb is not None and abs(ya - yb) > 1:
        return False
    return True


def _entry_titles(entry: MediaEntry) -> set:
    ts = {_norm_title(entry.canonical_title)}
    try:
        alts = json.loads(entry.alternative_titles or "[]")
    except (TypeError, ValueError):
        alts = []
    ts.update(_norm_title(t) for t in alts if t)
    ts.discard("")
    return ts


def find_media_entry_by_source(source: str, external_id: str, db: Session) -> Optional[MediaEntry]:
    ms = db.query(MediaSource).filter(
        MediaSource.source == source, MediaSource.external_id == external_id
    ).first()
    return ms.media_entry if ms else None


def _merge_item_into_entry(entry: MediaEntry, item: Item) -> None:
    """字段级 fallback 合并：只补缺口，不覆盖已有值。"""
    if not entry.canonical_title:
        entry.canonical_title = item.title
    alts = []
    try:
        alts = json.loads(entry.alternative_titles or "[]")
    except (TypeError, ValueError):
        alts = []
    for t in (item.title, item.alternative_title):
        if t and t != entry.canonical_title and t not in alts:
            alts.append(t)
    if alts:
        entry.alternative_titles = json.dumps(alts, ensure_ascii=False)

    if not entry.description:
        desc = _meta(item, "description") or item.content
        if desc:
            entry.description = desc
    if not entry.image_url and item.image_url:
        entry.image_url = item.image_url
    if not entry.work_type and item.work_type:
        entry.work_type = item.work_type
    if not entry.release_date and item.release_date:
        entry.release_date = item.release_date
    if not entry.year:
        entry.year = item_year(item)
    if not entry.genres:
        g = _meta(item, "genres") or []
        if g:
            entry.genres = json.dumps(list(g)[:12], ensure_ascii=False)
    if not entry.status:
        entry.status = _meta(item, "status")
    if not entry.episodes:
        entry.episodes = _meta(item, "episodes")
    if not entry.background:
        entry.background = _meta(item, "background")
    # Phase 12-C：高价值结构化字段（字段级 fallback，只补缺口）
    if not entry.duration:
        entry.duration = _meta(item, "duration")
    if not entry.season:
        entry.season = _meta(item, "season")
    if not entry.studios:
        s = _meta(item, "studios") or []
        if s:
            entry.studios = json.dumps(list(s)[:8], ensure_ascii=False)
    if not entry.themes:
        t = _meta(item, "themes") or []
        if t:
            entry.themes = json.dumps(list(t)[:12], ensure_ascii=False)
    if not entry.demographics:
        d = _meta(item, "demographics") or []
        if d:
            entry.demographics = json.dumps(list(d)[:6], ensure_ascii=False)
    if not entry.external_links:
        el = _meta(item, "external_links") or []
        if el:
            entry.external_links = json.dumps(list(el)[:10], ensure_ascii=False)


def ensure_media_for_item(item: Item, db: Session) -> Optional[MediaEntry]:
    """为外部 Item 建立/合并 MediaEntry + upsert MediaSource + 同步 Staff/MediaRelation。

    幂等、非致命；只更新该 Item 所属 Provider 的 Staff/Relation 行（Provider 隔离：
    刷新 Jikan 不会删 Bangumi 的 Staff）。原 raw_metadata 保留不动。
    """
    if item.source == "local" or not item.external_id:
        return None

    entry = find_media_entry_by_source(item.source, item.external_id, db)
    if entry is None:
        titles = _item_titles(item)
        entry = None
        for cand in db.query(MediaEntry).all():
            if (titles & _entry_titles(cand)
                    and _mergeable(cand.work_type, item.work_type, cand.year, item_year(item))):
                entry = cand
                break
        if entry is None:
            entry = MediaEntry(canonical_title=item.title)
            db.add(entry)
            db.flush()

    _merge_item_into_entry(entry, item)

    ms = db.query(MediaSource).filter(
        MediaSource.source == item.source, MediaSource.external_id == item.external_id
    ).first()
    if ms is None:
        ms = MediaSource(media_id=entry.id, source=item.source, external_id=item.external_id)
        db.add(ms)
    ms.source_title = item.title
    ms.image_url = item.image_url or ms.image_url
    ms.raw_metadata = item.raw_metadata
    ms.last_synced_at = datetime.now(timezone.utc)

    if item.media_id != entry.id:
        item.media_id = entry.id

    _sync_staff(entry, item, db)
    _sync_relations(entry, item, db)
    db.flush()
    return entry


def _sync_staff(entry: MediaEntry, item: Item, db: Session) -> None:
    """重建该 (MediaEntry, source) 的 Staff 索引（Provider 隔离，不删其它源）。"""
    db.query(Staff).filter(Staff.media_id == entry.id, Staff.source == item.source).delete()
    for i, s in enumerate(_meta_list(item, "staff") or []):
        if not isinstance(s, dict) or not s.get("name"):
            continue
        db.add(Staff(
            media_id=entry.id,
            source=item.source,
            external_id=str(s["external_id"]) if s.get("external_id") else None,
            name=str(s["name"]),
            role=s.get("role"),
            credit_order=s.get("credit_order") if s.get("credit_order") is not None else i,
            raw_metadata=s,
        ))


_RELATION_NORMALIZE = {
    "prequel": "prequel",
    "sequel": "sequel",
    "side story": "side_story",
    "spin off": "spin_off",
    "spin_off": "spin_off",
    "spinoff": "spin_off",
    "adaptation": "adaptation",
    "alternative": "alternative",
    "parent": "parent_story",
    "parent story": "parent_story",
    "parent_story": "parent_story",
    "other": "other",
}


def normalize_relation_type(raw) -> str:
    """关系类型标准化：已知类型 → 统一小写规范名；未知 → 'other'。

    原始值保留在 raw_metadata（不丢失、不强改 Provider 原文）。
    """
    if not raw:
        return "other"
    key = str(raw).strip().lower().replace("_", " ").replace("-", " ").strip()
    return _RELATION_NORMALIZE.get(key, "other")


def _sync_relations(entry: MediaEntry, item: Item, db: Session) -> None:
    """重建该 (MediaEntry, source) 的 MediaRelation 索引；绑定已收藏的 target_media_id。

    未知 relation_type 标准化为 'other'，原始值保留在 raw_metadata。
    """
    db.query(MediaRelation).filter(
        MediaRelation.media_id == entry.id, MediaRelation.source == item.source
    ).delete()
    for r in _meta_list(item, "relations") or []:
        if not isinstance(r, dict):
            continue
        title = r.get("title")
        if not title:
            continue
        target_src = r.get("source") or item.source
        target_eid = str(r["external_id"]) if r.get("external_id") is not None else None
        target_media_id = None
        if target_eid:
            tms = db.query(MediaSource).filter(
                MediaSource.source == target_src, MediaSource.external_id == target_eid
            ).first()
            if tms is not None:
                target_media_id = tms.media_id
        db.add(MediaRelation(
            media_id=entry.id,
            source=item.source,
            relation_type=normalize_relation_type(r.get("relation")),
            target_title=str(title),
            target_external_id=target_eid,
            target_source=target_src,
            target_media_id=target_media_id,
            raw_metadata=r,
        ))


# 关系目标的外部 URL 模板（确定性、仅用于"外部查看"入口；不抓取/不递归拉详情）
_RELATION_URL_TEMPLATES = {
    "bangumi": "https://bgm.tv/subject/{eid}",
    "anilist": "https://anilist.co/anime/{eid}",
    "jikan": "https://myanimelist.net/anime/{eid}",
    "vndb": "https://vndb.org/v{eid}",
    "moegirl": "https://zh.moegirl.org.cn/{title}",
}


def relation_external_url(source, external_id, title) -> Optional[str]:
    if not external_id and not title:
        return None
    tpl = _RELATION_URL_TEMPLATES.get(source or "")
    if not tpl:
        return None
    try:
        return tpl.format(eid=external_id, title=(title or "").replace(" ", "_"))
    except Exception:
        return None


def relations_out(entry: MediaEntry, db: Session) -> list:
    """MediaEntry 的关系输出（含导航字段 external_url/is_local/target_item_id）。

    只查本地数据，不触发任何 Provider 请求。
    """
    rows = db.query(MediaRelation).filter(MediaRelation.media_id == entry.id).all()
    # Phase 13-E：批量解析 target_media_id → item_id（一次 IN 查询，避免逐行 N+1）
    target_ids = {r.target_media_id for r in rows if r.target_media_id is not None}
    item_by_media = {}
    if target_ids:
        for it in db.query(Item).filter(Item.media_id.in_(target_ids)).all():
            item_by_media.setdefault(it.media_id, it.id)
    out = []
    for r in rows:
        target_item_id = item_by_media.get(r.target_media_id) if r.target_media_id is not None else None
        out.append({
            "id": r.id,
            "relation": r.relation_type,          # 兼容旧字段名
            "relation_type": r.relation_type,
            "title": r.target_title,
            "source": r.source,
            "external_id": r.target_external_id,
            "target_media_id": r.target_media_id,
            "target_item_id": target_item_id,
            "is_local": r.target_media_id is not None,
            "external_url": relation_external_url(
                r.target_source or r.source, r.target_external_id, r.target_title),
        })
    return out


def _union_meta(items: List[Item], key: str) -> list:
    """合并多个 Item 的某类 metadata 列表（characters/staff/relations），按 id/name 去重。"""
    out: list = []
    seen = set()
    for it in items:
        for x in (_meta(it, key) or []):
            if not isinstance(x, dict):
                continue
            ident = x.get("id") or x.get("name") or x.get("title")
            if ident is not None:
                if ident in seen:
                    continue
                seen.add(ident)
            out.append(x)
    return out


def media_detail(media_id: int, db: Session) -> Optional[dict]:
    """聚合单条 MediaEntry 的完整信息（字段级 fallback + 来源 + 关联 Item）。"""
    entry = db.get(MediaEntry, media_id)
    if entry is None:
        return None
    items = list(entry.items)

    try:
        alts = json.loads(entry.alternative_titles or "[]")
    except (TypeError, ValueError):
        alts = []
    try:
        genres = json.loads(entry.genres or "[]")
    except (TypeError, ValueError):
        genres = []
    try:
        studios = json.loads(entry.studios or "[]")
    except (TypeError, ValueError):
        studios = []
    try:
        themes = json.loads(entry.themes or "[]")
    except (TypeError, ValueError):
        themes = []
    try:
        demographics = json.loads(entry.demographics or "[]")
    except (TypeError, ValueError):
        demographics = []
    try:
        external_links = json.loads(entry.external_links or "[]")
    except (TypeError, ValueError):
        external_links = []

    ratings = [_meta(it, "rating") for it in items]
    ratings = [r for r in ratings if isinstance(r, (int, float))]
    rating = max(ratings) if ratings else None

    return {
        "id": entry.id,
        "canonical_title": entry.canonical_title,
        "alternative_titles": alts,
        "description": entry.description,
        "image_url": entry.image_url,
        "work_type": entry.work_type,
        "release_date": entry.release_date,
        "year": entry.year,
        "genres": genres,
        "status": entry.status,
        "episodes": entry.episodes,
        "background": entry.background,
        "duration": entry.duration,
        "season": entry.season,
        "studios": studios,
        "themes": themes,
        "demographics": demographics,
        "external_links": external_links,
        "rating": rating,
        "characters": _union_meta(items, "characters"),
        "staff": [{
            "id": s.id, "name": s.name, "role": s.role,
            "source": s.source, "external_id": s.external_id, "credit_order": s.credit_order,
        } for s in db.query(Staff).filter(Staff.media_id == entry.id)
            .order_by(Staff.credit_order.asc()).all()],
        "relations": relations_out(entry, db),
        "sources": [{
            "id": s.id,
            "source": s.source,
            "external_id": s.external_id,
            "external_url": s.external_url,
            "source_title": s.source_title,
            "image_url": s.image_url,
            "last_synced_at": s.last_synced_at,
        } for s in entry.sources],
        "items": [{
            "id": it.id, "title": it.title,
            "source": it.source, "external_id": it.external_id,
            "image_url": it.image_url,
        } for it in items],
    }
