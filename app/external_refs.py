"""外部资料本地化：完整资料文本构建 + external_reference chunk 重建 + 批量补齐

设计（详见 docs/decisions/0025-external-reference-rag.md）：
- 收藏外部条目时不再只存简介摘要，而是把"完整简介 + 基本信息 + 角色小传"
  下载后切分入库（source_type='external_reference'，connector=数据源名），
  让百科资料真正参与语义检索，同时与用户自己写的 note/review 严格区分；
- 检索层对 external_reference 加权压低（见 retrieval.py），避免挤掉用户
  自己的内容；
- 历史收藏用 `backfill_external_reference` 分批补齐（复用 Connector 的令牌桶
  限流，每次最多处理 limit 条，可重复调用继续推进）。
"""
import threading
from typing import List, Optional

from sqlalchemy.orm import Session

from app import vectorstore
from app.database import SessionLocal
from app.models import Chunk, Item


# ---------------------------------------------------------------- 完整资料文本

def build_reference_text(detail) -> str:
    """从 ItemDetail 构建完整参考文本（Markdown，供切分入库）。

    结构：作品简介 + 基本信息（原名/日期/标签等）+ 角色小传（每个角色一个
    ## 小节，含关系、小传、声优）。标题天然成为语义块边界（复用 ingest 的
    heading-aware 切分，见 ADR 0001）。
    """
    if detail is None:
        return ""
    parts: List[str] = []
    if detail.description and detail.description.strip():
        parts.append("# 作品简介\n\n" + detail.description.strip())

    meta = detail.metadata or {}
    info_lines: List[str] = []
    for key, label in (
        ("original_name", "原名"),
        ("date", "发售/播出日期"),
        ("type", "条目类型"),
        ("volumes", "卷数"),
        ("eps", "集数"),
        ("rating", "大众评分"),
        ("length", "页面长度"),
    ):
        v = meta.get(key)
        if v in (None, ""):
            continue
        info_lines.append(f"- {label}：{v}")
    if meta.get("tags"):
        info_lines.append("- 标签：" + "、".join(str(t) for t in meta["tags"][:12]))
    if info_lines:
        parts.append("# 基本信息\n\n" + "\n".join(info_lines))

    chars = meta.get("characters") or []
    if chars:
        char_blocks: List[str] = ["# 角色"]
        for c in chars:
            if not isinstance(c, dict):
                continue
            name = c.get("name")
            if not name:
                continue
            header = f"\n## {name}"
            if c.get("relation"):
                header += f"（{c['relation']}）"
            lines = [header]
            if c.get("summary"):
                lines.append("")
                lines.append(str(c["summary"]).strip())
            actors = c.get("actors") or []
            if actors:
                lines.append("")
                lines.append("声优：" + "、".join(str(a) for a in actors))
            char_blocks.append("\n".join(lines))
        parts.append("\n\n".join(char_blocks))

    return "\n\n".join(parts).strip()


# ---------------------------------------------------------------- raw_metadata 内 reference 存取

def get_stored_reference(item: Item) -> Optional[str]:
    """从 raw_metadata 读取已存的外部完整资料文本（ADR 0016 结构内嵌）。"""
    raw = item.raw_metadata
    if not isinstance(raw, dict):
        return None
    detail = raw.get("detail")
    if not isinstance(detail, dict):
        return None
    meta = detail.get("metadata")
    if not isinstance(meta, dict):
        return None
    text = meta.get("reference_text")
    return text if isinstance(text, str) else None


def with_reference_text(detail) -> dict:
    """构造统一 raw_metadata.detail 结构（ADR 0016），并把完整资料文本存入
    detail.metadata.reference_text，供重建 chunk 时判重与追溯。"""
    meta = dict(detail.metadata or {})
    meta["reference_text"] = build_reference_text(detail)
    return {
        "title": detail.title,
        "description": detail.description,
        "image_url": detail.image_url,
        "metadata": meta,
    }


# ---------------------------------------------------------------- chunk 重建

def _external_chunks(db: Session, item_id: int) -> List[Chunk]:
    return db.query(Chunk).filter(
        Chunk.item_id == item_id, Chunk.source_type == "external_reference"
    ).all()


def replace_external_reference_chunks(
    item: Item, reference_text: str, db: Optional[Session] = None
) -> int:
    """重建某外部条目的 external_reference 向量与 Chunk 行（先删后写）。

    用于：手动刷新/重新下载完整资料、历史收藏补齐。文本为空时不动已有
    chunk（退回仅存简介的情况，避免误删原有内容）。返回写入的 chunk 数。
    """
    own_session = db is None
    db = db or SessionLocal()
    try:
        if not reference_text or not reference_text.strip():
            return len(_external_chunks(db, item.id))

        refs = [c.embedding_ref for c in _external_chunks(db, item.id) if c.embedding_ref]
        if refs:
            try:
                vectorstore.get_collection().delete(ids=refs)
            except Exception:
                pass  # 向量清理失败不阻塞，见 ingest 同类处理
        db.query(Chunk).filter(
            Chunk.item_id == item.id, Chunk.source_type == "external_reference"
        ).delete(synchronize_session=False)
        db.flush()

        from app.ingest import _write_external_reference_chunks
        ids = _write_external_reference_chunks(item, reference_text, db)
        db.commit()
        return len(ids)
    finally:
        if own_session:
            db.close()


def ensure_external_reference_chunks(
    item: Item, reference_text: str, db: Optional[Session] = None
) -> bool:
    """确保外部条目的 external_reference chunk 与当前参考文本一致。

    已一致（chunk 存在且 raw_metadata 里的 reference_text 相同）→ 返回 False
    不做任何写入；否则重建。用于收藏入库路径，避免重复 re-embedding。
    """
    own_session = db is None
    db = db or SessionLocal()
    try:
        if _external_chunks(db, item.id) and get_stored_reference(item) == reference_text:
            return False
        replace_external_reference_chunks(item, reference_text, db=db)
        return True
    finally:
        if own_session:
            db.close()


# ---------------------------------------------------------------- 历史收藏批量补齐

_backfill_lock = threading.Lock()
_backfill_running = False


def backfill_external_reference(
    limit: int = 5, source: Optional[str] = None, db: Optional[Session] = None
) -> int:
    """给缺少完整参考资料的外部条目补齐：下载详情 → 构建文本 → 重建 chunk。

    - 复用各 Connector 的令牌桶限流（get_detail 内部 acquire），不另起限流，
      避免不受控批量拉取（教训：同步阻塞 119 秒事件）；
    - 每次最多处理 `limit` 条，可重复调用继续推进（缺哪条补哪条，已补齐跳过）；
    - 单条失败跳过，不阻塞整体；同步版本供脚本/线程池直接调用。
    返回本次补齐条数。
    """
    from app.connectors import registry

    own_session = db is None
    db = db or SessionLocal()
    try:
        query = db.query(Item).filter(
            Item.source != "local", Item.external_id.isnot(None)
        )
        if source:
            query = query.filter(Item.source == source)
        items = query.all()
        pending = [it for it in items if not get_stored_reference(it)][:limit]

        conns: dict = {}
        filled = 0
        for it in pending:
            conn = conns.get(it.source) or registry.get_connector(it.source)
            if conn is None:
                continue
            capabilities = getattr(getattr(conn, "manifest", None), "capabilities", []) or []
            if "get_detail" not in capabilities:
                continue
            try:
                detail = conn.get_detail(it.external_id)
                text = build_reference_text(detail)
                # 回填 raw_metadata（含 reference_text），供判重与角色墙聚合
                raw = it.raw_metadata if isinstance(it.raw_metadata, dict) else {}
                raw = dict(raw)
                raw["source"] = it.source
                raw["detail"] = with_reference_text(detail)
                it.raw_metadata = raw
                if not it.image_url and detail.image_url:
                    it.image_url = detail.image_url
                db.flush()
                replace_external_reference_chunks(it, text, db=db)
                db.commit()
                filled += 1
            except Exception:  # noqa: BLE001 - 单条失败跳过，下轮再补
                db.rollback()
                continue
        return filled
    finally:
        if own_session:
            db.close()


def backfill_async(limit: int = 5, source: Optional[str] = None) -> bool:
    """非阻塞触发批量补齐（单飞：已在跑则不重复启动），供 API/角色墙刷新用。

    返回是否本次实际启动了后台任务。
    """
    global _backfill_running
    with _backfill_lock:
        if _backfill_running:
            return False
        _backfill_running = True

    def _run():
        try:
            backfill_external_reference(limit=limit, source=source)
        finally:
            global _backfill_running
            with _backfill_lock:
                _backfill_running = False

    threading.Thread(target=_run, daemon=True).start()
    return True
