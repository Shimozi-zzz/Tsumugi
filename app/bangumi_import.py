"""Bangumi 收藏批量导入（OAuth 已授权后）

设计（详见 ADR 0022）：
- 分页拉取用户收藏（复用 BangumiConnector.get_collections → 令牌桶限流 + 代理）；
- 每条收藏 → `ingest_external` 幂等入库为本地 Item（**不拉角色详情**——几百条
  逐条拉角色会请求量爆炸，角色改为"查看角色墙时懒加载补详情"，见
  `backfill_bangumi_details`）；
- 追番状态 + Bangumi 个人评分 → 自动 Review（source="bangumi_collection"，
  去重：同 item 同 source 只一条，重复导入时原地更新 rating/status）；
- 进度：后台线程跑，job 状态可轮询。
"""
import threading
from typing import Dict, List, Optional

from app.models import Item, Review

BANGUMI_TYPE_TO_STATUS = {1: "想看", 2: "看完", 3: "在看", 4: "搁置", 5: "弃坑"}
BANGUMI_IMPORT_SOURCE = "bangumi_collection"
BANGUMI_IMPORT_TITLE = "从 Bangumi 导入"
PAGE_LIMIT = 30

_jobs: Dict[str, dict] = {}
_jobs_lock = threading.Lock()
_job_seq = 0


# ---------------------------------------------------------------- job 管理

def new_job() -> str:
    global _job_seq
    with _jobs_lock:
        _job_seq += 1
        job_id = f"bgimport-{_job_seq}"
        _jobs[job_id] = {
            "state": "pending", "total": 0, "current": 0,
            "imported": 0, "skipped": 0, "failed": 0,
            "failures": [], "message": "",
        }
        return job_id


def get_job(job_id: str) -> Optional[dict]:
    with _jobs_lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None


def _update(job_id: str, **kw) -> None:
    with _jobs_lock:
        j = _jobs.get(job_id)
        if j:
            j.update(kw)


def start_import(access_token: str) -> str:
    job_id = new_job()
    _update(job_id, state="running")
    thread = threading.Thread(target=_run_import, args=(job_id, access_token), daemon=True)
    thread.start()
    return job_id


# ---------------------------------------------------------------- 导入循环

def _run_import(job_id: str, access_token: str) -> None:
    from app.connectors import registry
    from app.database import SessionLocal

    conn = registry.get_connector("bangumi")
    if conn is None:
        _update(job_id, state="error", message="bangumi connector 未注册")
        return

    db = SessionLocal()
    try:
        offset = 0
        total = 0
        first = conn.get_collections(access_token, offset=0, limit=PAGE_LIMIT)
        total = int(first.get("total") or 0)
        _update(job_id, total=total)
        _import_page(job_id, first.get("data") or [], db)

        offset += PAGE_LIMIT
        while offset < total:
            page = conn.get_collections(access_token, offset=offset, limit=PAGE_LIMIT)
            entries = page.get("data") or []
            _import_page(job_id, entries, db)
            offset += PAGE_LIMIT

        job = get_job(job_id)
        _update(job_id, state="done",
                message=f"导入 {job['imported']} 条，跳过 {job['skipped']} 条重复，失败 {job['failed']} 条")
    except Exception as e:  # noqa: BLE001 - 后台任务兜底
        _update(job_id, state="error", message=str(e))
    finally:
        db.close()


def _import_page(job_id: str, entries: List[dict], db) -> None:
    from app import ingest

    job = get_job(job_id)
    imported, skipped, failed = job["imported"], job["skipped"], job["failed"]
    failures = list(job["failures"])

    for entry in entries:
        job = get_job(job_id)
        try:
            subject = entry.get("subject") or {}
            subject_id = str(entry.get("subject_id") or subject.get("id") or "")
            if not subject_id:
                failed += 1
                failures.append("缺少 subject_id")
                continue
            title = subject.get("name_cn") or subject.get("name") or f"Bangumi {subject_id}"
            summary = subject.get("short_summary") or ""
            images = subject.get("images") or {}
            img = images.get("large") or images.get("medium") or images.get("common")
            raw_tags = subject.get("tags") or []
            tags = [t.get("name") if isinstance(t, dict) else str(t) for t in raw_tags if t]

            # 去重：已存在条目 → 记 skipped（review 原地更新），不重建
            existing = db.query(Item).filter(
                Item.source == "bangumi", Item.external_id == subject_id
            ).first()
            if existing is not None:
                _upsert_collection_review(db, existing, entry)
                skipped += 1
            else:
                item = ingest.ingest_external(
                    source="bangumi", external_id=subject_id, title=title,
                    content=summary, image_url=img, tags=tags, db=db,
                )
                _upsert_collection_review(db, item, entry)
                imported += 1
        except Exception as e:  # 单条失败不阻塞整体
            failed += 1
            failures.append(f"{subject_id}: {e}")

        _update(job_id, current=job["current"] + 1,
                imported=imported, skipped=skipped, failed=failed,
                failures=failures[-20:])


def _upsert_collection_review(db, item: Item, entry: dict) -> Review:
    """追番状态 + Bangumi 个人评分 → 自动 Review（去重：同 item 同 source 一条）。"""
    status = BANGUMI_TYPE_TO_STATUS.get(entry.get("type"))
    rate = entry.get("rate")
    rating = rate if isinstance(rate, int) and 0 < rate <= 10 else None

    existing = db.query(Review).filter(
        Review.item_id == item.id, Review.source == BANGUMI_IMPORT_SOURCE
    ).first()
    if existing is not None:
        existing.rating = rating
        existing.status = status
        db.commit()
        db.refresh(existing)
        return existing

    review = Review(
        item_id=item.id, title=BANGUMI_IMPORT_TITLE, content="",
        rating=rating, status=status, spoiler=0, source=BANGUMI_IMPORT_SOURCE,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


# ---------------------------------------------------------------- 角色懒加载补详情

def _needs_detail(item: Item) -> bool:
    raw = item.raw_metadata
    if not isinstance(raw, dict):
        return True
    return not isinstance(raw.get("detail"), dict)


_backfill_lock = threading.Lock()
_backfill_running = False


def backfill_async(limit: int = 10) -> bool:
    """非阻塞触发角色懒补（单飞：已在跑则不重复启动），避免角色墙响应被阻塞。

    批量导入的条目在用户查看角色墙时逐步补详情；受令牌桶限流约束，每次后台
    补 limit 条。返回是否本次实际启动了后台任务。
    """
    global _backfill_running
    with _backfill_lock:
        if _backfill_running:
            return False
        _backfill_running = True

    def _run():
        try:
            backfill_bangumi_details(limit=limit)
        finally:
            global _backfill_running
            with _backfill_lock:
                _backfill_running = False

    threading.Thread(target=_run, daemon=True).start()
    return True


def backfill_bangumi_details(limit: int = 20) -> int:
    """角色墙懒加载：给缺少 raw_metadata.detail 的 bangumi 条目补拉详情。

    每次最多补 limit 条（受令牌桶限流约束，分批推进）；失败跳过不阻塞。
    避免"批量导入时就逐条拉角色"导致几百个请求一次打爆限流。
    """
    from app.connectors import registry
    from app.database import SessionLocal

    conn = registry.get_connector("bangumi")
    if conn is None:
        return 0
    db = SessionLocal()
    filled = 0
    try:
        items = db.query(Item).filter(Item.source == "bangumi").all()
        pending = [it for it in items if _needs_detail(it)][:limit]
        for it in pending:
            try:
                detail = conn.get_detail(it.external_id)
                it.raw_metadata = {
                    "source": "bangumi",
                    "detail": {
                        "title": detail.title,
                        "description": detail.description,
                        "image_url": detail.image_url,
                        "metadata": detail.metadata,
                    },
                }
                if not it.image_url:
                    it.image_url = detail.image_url
                db.commit()
                filled += 1
            except Exception:  # noqa: BLE001 - 单条失败跳过
                continue
        return filled
    finally:
        db.close()
