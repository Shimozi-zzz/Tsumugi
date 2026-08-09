"""图书馆数据备份/导出/导入（ADR 0038）

技术债兑现：AGENTS.md"未来扩展点"里"本地库数据导出/备份"。
- 导出格式：单个 JSON 文档（含 schema version），内容 = 本地笔记 + Review +
  Item 元数据（含 raw_metadata 下载资料）+ 标签 + Connector 配置（不含明文密钥，
  config_ref 只存环境变量占位符）+ LLM Provider 配置（api_key_ref 同为占位符）；
- 向量库（Chroma）**不导出**：可从原始内容重新生成（导入时重建 chunk + embedding），
  且体积大、与库版本强耦合；
- 导入：幂等合并——外部条目按 (source, external_id)、本地笔记按 content_hash 去重，
  命中则刷新元数据（不重建向量），未命中则新建并重建向量；Review 按
  (item_id, title, content) 去重；标签/数据源/Provider 按 name 幂等。
"""
import json
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Item, LLMProviderConfig, Review, Source, Tag

FORMAT = "tsumugi-library"
VERSION = 1

_jobs: Dict[str, dict] = {}
_jobs_lock = threading.Lock()
_job_seq = 0


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def _parse_dt(s) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------- 导出

def export_backup(db: Session) -> dict:
    items = db.query(Item).order_by(Item.id).all()
    reviews = db.query(Review).order_by(Review.id).all()
    tags = db.query(Tag).order_by(Tag.id).all()
    sources = db.query(Source).order_by(Source.id).all()
    providers = db.query(LLMProviderConfig).order_by(LLMProviderConfig.id).all()
    return {
        "format": FORMAT,
        "version": VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "items": [
                {
                    "id": it.id, "title": it.title, "type": it.type, "content": it.content,
                    "file_path": it.file_path, "content_hash": it.content_hash,
                    "image_url": it.image_url, "source": it.source, "external_id": it.external_id,
                    "raw_metadata": it.raw_metadata,
                    "synced_at": _iso(it.synced_at),
                    "created_at": _iso(it.created_at), "updated_at": _iso(it.updated_at),
                    "tags": [t.name for t in it.tags],
                }
                for it in items
            ],
            "reviews": [
                {
                    "id": r.id, "item_id": r.item_id, "title": r.title, "content": r.content,
                    "rating": r.rating, "status": r.status, "spoiler": r.spoiler,
                    "source": r.source, "font_size": r.font_size,
                    "created_at": _iso(r.created_at), "updated_at": _iso(r.updated_at),
                }
                for r in reviews
            ],
            "tags": [{"id": t.id, "name": t.name} for t in tags],
            "sources": [
                {
                    "id": s.id, "name": s.name, "type": s.type, "enabled": s.enabled,
                    "config_ref": s.config_ref, "created_at": _iso(s.created_at),
                }
                for s in sources
            ],
            "llm_providers": [
                {
                    "id": p.id, "name": p.name, "provider_type": p.provider_type,
                    "base_url": p.base_url, "model_id": p.model_id,
                    "api_key_ref": p.api_key_ref, "enabled": p.enabled,
                }
                for p in providers
            ],
        },
    }


# ---------------------------------------------------------------- 导入

def _extract_reference(raw_metadata) -> Optional[str]:
    """从 raw_metadata 提取完整资料文本（ADR 0025 的 reference_text），供重建向量。"""
    if not isinstance(raw_metadata, dict):
        return None
    detail = raw_metadata.get("detail")
    if not isinstance(detail, dict):
        return None
    meta = detail.get("metadata")
    if not isinstance(meta, dict):
        return None
    rt = meta.get("reference_text")
    return rt if isinstance(rt, str) else None


def _find_item(db: Session, exp: dict) -> Optional[Item]:
    if exp.get("source") != "local" and exp.get("external_id"):
        return db.query(Item).filter(
            Item.source == exp["source"], Item.external_id == exp["external_id"]
        ).first()
    if exp.get("content_hash"):
        return db.query(Item).filter(Item.content_hash == exp["content_hash"]).first()
    return db.query(Item).filter(
        Item.title == exp.get("title"), Item.content == exp.get("content")
    ).first()


def _apply_tag_names(item: Item, names: List[str], tag_by_name: Dict[str, Tag]) -> None:
    item.tags = [tag_by_name[n] for n in names if n in tag_by_name]


def run_import(data: dict, db: Session) -> dict:
    """导入备份 JSON（幂等合并）。返回统计 {items_imported, items_updated,
    reviews_imported, reviews_skipped, tags_imported, sources_imported, ...}。"""
    if data.get("format") != FORMAT:
        raise ValueError(f"不是有效的 Tsumugi 备份文件（format={data.get('format')}）")
    payload = data.get("data") or {}

    stats = {
        "items_imported": 0, "items_updated": 0, "reviews_imported": 0,
        "reviews_skipped": 0, "tags_imported": 0, "sources_imported": 0,
        "providers_imported": 0,
    }

    # 1) 标签：按 name 幂等
    tag_by_name: Dict[str, Tag] = {}
    for t in payload.get("tags", []):
        name = (t.get("name") or "").strip()
        if not name or name in tag_by_name:
            continue
        tag = db.query(Tag).filter(Tag.name == name).first()
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
            stats["tags_imported"] += 1
        tag_by_name[name] = tag

    # 2) 条目：外部按 (source,external_id)、本地按 content_hash 去重；命中刷新元数据，
    #    未命中重建（含向量）
    item_map: Dict[int, int] = {}
    for exp in payload.get("items", []):
        existing = _find_item(db, exp)
        if existing is not None:
            existing.title = exp.get("title") or existing.title
            if exp.get("content") is not None:
                existing.content = exp["content"]
            if exp.get("image_url") is not None:
                existing.image_url = exp["image_url"]
            existing.raw_metadata = exp.get("raw_metadata")
            if exp.get("synced_at"):
                existing.synced_at = _parse_dt(exp["synced_at"])
            _apply_tag_names(existing, exp.get("tags") or [], tag_by_name)
            item_map[exp["id"]] = existing.id
            stats["items_updated"] += 1
            continue

        from app import ingest
        item = None
        if exp.get("type") == "image":
            item = ingest.ingest_image(
                exp.get("title") or "未命名", exp.get("file_path") or "",
                tag_names=exp.get("tags"), db=db,
            )
        elif exp.get("source") != "local":
            item = ingest.ingest_external(
                source=exp.get("source") or "external",
                external_id=str(exp.get("external_id") or ""),
                title=exp.get("title") or "未命名",
                content=exp.get("content") or "",
                image_url=exp.get("image_url"),
                tags=exp.get("tags"),
                raw_metadata=exp.get("raw_metadata"),
                reference_text=_extract_reference(exp.get("raw_metadata")),
                db=db,
            )
        else:
            item = ingest.ingest_text_document(
                exp.get("title") or "未命名", exp.get("content") or "",
                tag_names=exp.get("tags"), db=db,
            )
        # 保留原始时间戳
        item.created_at = _parse_dt(exp.get("created_at")) or item.created_at
        if exp.get("synced_at"):
            item.synced_at = _parse_dt(exp["synced_at"])
        db.commit()
        db.refresh(item)
        item_map[exp["id"]] = item.id
        stats["items_imported"] += 1

    # 3) Review：按 (item_id, title, content) 去重，未命中重建（含向量）
    from app import reviews
    for r in payload.get("reviews", []):
        mid = item_map.get(r.get("item_id"))
        if mid is None:
            continue
        dup = db.query(Review).filter(
            Review.item_id == mid,
            Review.title == r.get("title"),
            Review.content == r.get("content"),
        ).first()
        if dup is not None:
            stats["reviews_skipped"] += 1
            continue
        created = reviews.create_review(
            mid, r.get("content") or "", title=r.get("title"),
            rating=r.get("rating"), status=r.get("status"),
            spoiler=bool(r.get("spoiler")), font_size=r.get("font_size"), db=db,
        )
        created.created_at = _parse_dt(r.get("created_at")) or created.created_at
        db.commit()
        stats["reviews_imported"] += 1

    # 4) 数据源（声明式配置/通用设置/插件确认，均为非明文占位符）
    from app.connectors import persistence
    for s in payload.get("sources", []):
        name = (s.get("name") or "").strip()
        if not name:
            continue
        row = db.query(Source).filter(Source.name == name).first()
        if row is None:
            row = Source(name=name, type=s.get("type") or "connector")
            db.add(row)
            stats["sources_imported"] += 1
        row.type = s.get("type") or row.type
        row.config_ref = s.get("config_ref")
        row.enabled = 1 if s.get("enabled", 1) else 0
        db.commit()

    # 5) LLM Provider 配置（api_key_ref 为占位符，不含明文）
    for p in payload.get("llm_providers", []):
        name = (p.get("name") or "").strip()
        if not name:
            continue
        row = db.query(LLMProviderConfig).filter(LLMProviderConfig.name == name).first()
        if row is None:
            row = LLMProviderConfig(name=name)
            db.add(row)
            stats["providers_imported"] += 1
        row.provider_type = p.get("provider_type") or row.provider_type
        row.base_url = p.get("base_url") or row.base_url
        row.model_id = p.get("model_id") or row.model_id
        row.api_key_ref = p.get("api_key_ref")
        row.enabled = 1 if p.get("enabled") else 0
        db.commit()

    return stats


# ---------------------------------------------------------------- 后台任务（导入进度）

def new_job() -> str:
    global _job_seq
    with _jobs_lock:
        _job_seq += 1
        job_id = f"bkimport-{_job_seq}"
        _jobs[job_id] = {
            "state": "pending", "total": 0, "current": 0,
            "imported": 0, "updated": 0, "skipped": 0, "message": "",
        }
        return job_id


def get_job(job_id: str) -> Optional[dict]:
    with _jobs_lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None


def start_import(data: dict) -> str:
    """后台线程导入（大数据量不阻塞前端；进度轮询 /backup/import/status）。"""
    job_id = new_job()
    total = len(((data.get("data") or {}).get("items") or []))
    with _jobs_lock:
        _jobs[job_id]["total"] = total
        _jobs[job_id]["state"] = "running"
    thread = threading.Thread(target=_run_import, args=(job_id, data), daemon=True)
    thread.start()
    return job_id


def _run_import(job_id: str, data: dict) -> None:
    # 函数体内 import：与 routes._ingest_sync 一致，测试 patch 时能覆盖（坑位 #22 变体）
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        stats = run_import(data, db)
        with _jobs_lock:
            _jobs[job_id].update(
                state="done", imported=stats.get("items_imported", 0),
                updated=stats.get("items_updated", 0),
                skipped=stats.get("reviews_skipped", 0),
                message=f"导入完成：新条目 {stats['items_imported']}，更新 {stats['items_updated']}，"
                        f"书评 {stats['reviews_imported']}，跳过 {stats['reviews_skipped']}",
            )
    except Exception as e:  # noqa: BLE001 - 后台任务兜底
        with _jobs_lock:
            _jobs[job_id].update(state="error", message=str(e))
    finally:
        db.close()
