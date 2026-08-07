"""文档切分与入库模块

策略要点（详见 docs/decisions/0001-text-chunking-strategy.md）：
- 以"段落 + Markdown 标题"为天然语义块，贪心打包进 chunk，尽量保持语义完整；
- 单个超长块按句子边界硬切分；
- 相邻 chunk 之间保留 overlap 字符，缓解边界上下文割裂。
"""
import hashlib
import os
import re
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app import embeddings, vectorstore
from app.config import settings
from app.database import SessionLocal
from app.models import Chunk, Item, Tag, item_tag_association

HEADING_RE = re.compile(r"^#{1,6}\s+\S")
SENTENCE_END_RE = re.compile(r"[。！？!?；;，,.．…\n]")


# ---------------------------------------------------------------- 切分核心

def _split_blocks(text: str) -> List[str]:
    """按空行拆分为段落；段落内再按 Markdown 标题行拆开（标题单独成块）。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks: List[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        lines = paragraph.split("\n")
        current: List[str] = []
        for line in lines:
            if HEADING_RE.match(line) and current:
                blocks.append("\n".join(current).strip())
                current = [line]
            else:
                current.append(line)
        if current:
            blocks.append("\n".join(current).strip())
    return blocks


def _tail_overlap(previous: str, chunk_overlap: int) -> str:
    """取上一 chunk 末尾 chunk_overlap 个字符作为下一 chunk 的前缀。"""
    if chunk_overlap <= 0:
        return ""
    return previous[-chunk_overlap:].lstrip("\n")


def _split_oversized(block: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    """单个超大块：优先在句子边界切，其次空白处，最后硬切；带 overlap。"""
    segments: List[str] = []
    start = 0
    n = len(block)
    min_cut = max(chunk_size // 2, 1)
    while start < n:
        end = min(start + chunk_size, n)
        if end == n:
            segments.append(block[start:end])
            break
        cut = end
        # 在 [start+min_cut, end) 内从后往前找句子边界
        for i in range(end - 1, start + min_cut - 1, -1):
            if SENTENCE_END_RE.match(block[i]):
                cut = i + 1
                break
        segments.append(block[start:cut])
        next_start = max(cut - chunk_overlap, start + 1)
        if next_start >= n:
            break
        start = next_start
    return [s for s in segments if s.strip()]


def split_text(
    text: str,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> List[str]:
    """把文本切分为不超过 chunk_size 字符的 chunk 列表（按原文档顺序）。

    Args:
        text: 原始文本（markdown 或纯文本）。
        chunk_size: 单块最大字符数，None 时取 settings.chunk_size。
        chunk_overlap: 相邻块重叠字符数，None 时取 settings.chunk_overlap；
                      会被钳制到不超过 chunk_size // 2。
    """
    if not text or not text.strip():
        return []
    text = text.lstrip("\ufeff")  # 去除 UTF-8 BOM
    chunk_size = settings.chunk_size if chunk_size is None else chunk_size
    chunk_overlap = settings.chunk_overlap if chunk_overlap is None else chunk_overlap
    if chunk_size <= 0:
        chunk_size = settings.chunk_size
    chunk_overlap = min(max(chunk_overlap, 0), chunk_size // 2)

    blocks = _split_blocks(text)
    chunks: List[str] = []
    current = ""

    for block in blocks:
        if len(block) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_oversized(block, chunk_size, chunk_overlap))
            continue

        if current:
            candidate = current + "\n\n" + block
            if len(candidate) <= chunk_size:
                current = candidate
                continue
            chunks.append(current)
            current = ""

        if chunks and chunk_overlap > 0:
            current = _tail_overlap(chunks[-1], chunk_overlap)
            if current:
                current += "\n\n"
        current += block

    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------- 标签辅助

def _get_or_create_tag(db: Session, name: str) -> Optional[Tag]:
    name = name.strip()
    if not name:
        return None
    tag = db.query(Tag).filter(Tag.name == name).first()
    if tag is None:
        tag = Tag(name=name)
        db.add(tag)
    return tag


def _apply_tags(db: Session, item: Item, tag_names: Optional[List[str]]) -> None:
    if not tag_names:
        return
    seen = set()
    for name in tag_names:
        tag = _get_or_create_tag(db, name)
        if tag is not None and tag.name not in seen:
            seen.add(tag.name)
            item.tags.append(tag)


# ---------------------------------------------------------------- 去重指纹

def compute_bytes_hash(data: bytes) -> str:
    """对任意字节内容计算 sha256 指纹。"""
    return hashlib.sha256(data).hexdigest()


def compute_content_hash(content: str) -> str:
    """文本内容的去重指纹（UTF-8 编码后 sha256）。"""
    return compute_bytes_hash(content.encode("utf-8"))


def compute_file_hash(file_path: str) -> Optional[str]:
    """文件内容的去重指纹；文件不可读时返回 None（不参与判重）。"""
    try:
        with open(file_path, "rb") as f:
            return compute_bytes_hash(f.read())
    except OSError:
        return None


def find_existing_by_hash(db: Session, content_hash: str) -> Optional[Item]:
    """按去重指纹查找已存在的条目（用于重复导入跳过）。"""
    if not content_hash:
        return None
    return db.query(Item).filter(Item.content_hash == content_hash).first()


# ---------------------------------------------------------------- 入库

def ingest_text_document(
    title: str,
    content: str,
    tag_names: Optional[List[str]] = None,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    db: Optional[Session] = None,
    force: bool = False,
) -> Item:
    """导入文本文档：切分 -> embedding -> 写入 Chroma + SQLite。

    默认按内容指纹去重：内容已存在时直接返回已有条目（不重复建向量）；
    force=True 时强制再导入一份。

    任一环节失败都会回滚数据库并清理已写入的向量，避免半成品数据。
    """
    own_session = db is None
    db = db or SessionLocal()
    try:
        chunks = split_text(content, chunk_size, chunk_overlap)
        content_hash = compute_content_hash(content)

        if not force:
            existing = find_existing_by_hash(db, content_hash)
            if existing is not None:
                return existing

        item = Item(
            title=title, type="note", content=content,
            source="local", content_hash=content_hash,
        )
        _apply_tags(db, item, tag_names)

        chroma_ids: List[str] = []
        db.add(item)
        db.flush()  # 拿到 item.id

        if chunks:
            vectors = embeddings.embed_texts(chunks)  # 可能抛 EmbeddingError
            ids = [f"item{item.id}_chunk{i}" for i in range(len(chunks))]
            metadatas = [
                {"item_id": item.id, "chunk_index": i} for i in range(len(chunks))
            ]
            vectorstore.get_collection().add(
                ids=ids,
                embeddings=vectors,
                documents=chunks,
                metadatas=metadatas,
            )
            chroma_ids = ids
            for i, (content, ref) in enumerate(zip(chunks, ids)):
                db.add(
                    Chunk(
                        item_id=item.id,
                        content=content,
                        chunk_index=i,
                        embedding_ref=ref,
                    )
                )

        db.commit()
        db.refresh(item)
        return item
    except Exception:
        db.rollback()
        # 反向清理已写入 Chroma 的向量，避免"库里有向量、SQLite 没记录"的孤儿
        if chroma_ids:
            try:
                vectorstore.get_collection().delete(ids=chroma_ids)
            except Exception:
                pass  # 清理失败不掩盖原始异常
        raise
    finally:
        if own_session:
            db.close()


def ingest_image(
    title: str,
    file_path: str,
    tag_names: Optional[List[str]] = None,
    db: Optional[Session] = None,
    force: bool = False,
) -> Item:
    """图片入库：仅存路径 + 元数据，不切分、不做语义检索（Phase 1 范围）。

    默认按文件内容指纹去重（路径不同但内容相同也算重复）；
    force=True 时强制再入库一份。"""
    own_session = db is None
    db = db or SessionLocal()
    file_hash = compute_file_hash(file_path)

    if not force and file_hash:
        existing = find_existing_by_hash(db, file_hash)
        if existing is not None:
            return existing

    item = Item(
        title=title, type="image", file_path=file_path,
        source="local", content_hash=file_hash,
    )
    _apply_tags(db, item, tag_names)
    try:
        db.add(item)
        db.commit()
        db.refresh(item)
        return item
    except Exception:
        db.rollback()
        raise
    finally:
        if own_session:
            db.close()


def ingest_external(
    source: str,
    external_id: str,
    title: str,
    content: str = "",
    image_url: Optional[str] = None,
    tags: Optional[List[str]] = None,
    raw_metadata: Optional[dict] = None,
    db: Optional[Session] = None,
) -> Item:
    """外部数据收藏入库（Phase 3 / Save to Library）。

    仅存摘要/简介文本进入向量库参与 RAG 检索，不做全文抓取存储。
    同一 source+external_id 重复收藏时返回已有条目（幂等）。
    """
    own_session = db is None
    db = db or SessionLocal()
    try:
        existing = (
            db.query(Item)
            .filter(Item.source == source, Item.external_id == external_id)
            .first()
        )
        if existing is not None:
            # 幂等命中：刷新同步时间，反映"最近一次收藏"的时间点
            existing.synced_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(existing)
            return existing

        content_hash = compute_content_hash(content or title)
        item = Item(
            title=title,
            type="external_ref",
            content=content,
            image_url=image_url,
            source=source,
            external_id=external_id,
            raw_metadata=raw_metadata,
            content_hash=content_hash,
            synced_at=datetime.now(timezone.utc),
        )
        _apply_tags(db, item, tags)

        chroma_ids: List[str] = []
        try:
            db.add(item)
            db.flush()
            chunks = split_text(content) if content else []
            if chunks:
                vectors = embeddings.embed_texts(chunks)
                ids = [f"item{item.id}_chunk{i}" for i in range(len(chunks))]
                metadatas = [
                    {"item_id": item.id, "chunk_index": i} for i in range(len(chunks))
                ]
                vectorstore.get_collection().add(
                    ids=ids, embeddings=vectors, documents=chunks, metadatas=metadatas,
                )
                chroma_ids = ids
                for i, (chunk_text, ref) in enumerate(zip(chunks, ids)):
                    db.add(
                        Chunk(
                            item_id=item.id, content=chunk_text,
                            chunk_index=i, embedding_ref=ref,
                        )
                    )
            db.commit()
            db.refresh(item)
            return item
        except Exception:
            db.rollback()
            if chroma_ids:
                try:
                    vectorstore.get_collection().delete(ids=chroma_ids)
                except Exception:
                    pass
            raise
    finally:
        if own_session:
            db.close()


def set_item_tags(
    item_id: int,
    tag_names: Optional[List[str]],
    mode: str = "add",
    db: Optional[Session] = None,
) -> Item:
    """给条目增/删/设置标签（单条或批量复用）。mode: add=追加 / remove=移除 /
    set=替换为给定集合。返回刷新后的 Item。"""
    own_session = db is None
    db = db or SessionLocal()
    try:
        item = db.get(Item, item_id)
        if item is None:
            raise ValueError(f"item {item_id} 不存在")
        names = [n.strip() for n in (tag_names or []) if n and n.strip()]
        if mode == "set":
            item.tags = []
            _apply_tags(db, item, names)
        elif mode == "remove":
            remove_names = set(names)
            item.tags = [t for t in item.tags if t.name not in remove_names]
        else:  # add
            _apply_tags(db, item, names)
        db.commit()
        db.refresh(item)
        if mode in ("remove", "set"):
            _cleanup_orphan_tags(db)
        return item
    finally:
        if own_session:
            db.close()


def delete_items(item_ids: List[int], db: Optional[Session] = None) -> int:
    """批量删除条目（复用 delete_item 的向量/附件/孤儿标签清理）。返回删除数。"""
    own_session = db is None
    db = db or SessionLocal()
    try:
        deleted = 0
        for iid in item_ids:
            if delete_item(iid, db=db):
                deleted += 1
        return deleted
    finally:
        if own_session:
            db.close()


def delete_item(item_id: int, db: Optional[Session] = None) -> bool:
    """删除条目：先删 Chroma 向量，再删 SQLite 记录（chunks 级联删除），
    最后清理不再被任何条目引用的孤立标签；图片条目同时删除本地附件文件。"""
    db = db or SessionLocal()
    item = db.get(Item, item_id)
    if item is None:
        return False

    refs = [c.embedding_ref for c in item.chunks if c.embedding_ref]
    if refs:
        try:
            vectorstore.get_collection().delete(ids=refs)
        except Exception:
            pass  # 向量清理失败不阻塞元数据删除，留待后续重建

    # 删除图片附件文件（仅限 upload_dir 内的文件，避免误删任意路径）
    if item.type == "image" and item.file_path:
        _delete_upload_file(item.file_path)

    db.delete(item)
    db.commit()
    _cleanup_orphan_tags(db)
    return True


def _delete_upload_file(file_path: str) -> None:
    """删除上传目录内的附件文件；路径越界时静默跳过。"""
    try:
        upload_root = os.path.abspath(settings.upload_dir)
        abs_path = os.path.abspath(file_path)
        if os.path.commonpath([upload_root, abs_path]) != upload_root:
            return
        if os.path.isfile(abs_path):
            os.remove(abs_path)
    except (OSError, ValueError):
        pass  # 文件已不存在或删除失败不阻塞条目删除


def _cleanup_orphan_tags(db: Session) -> None:
    """删除未被任何 Item 引用的 Tag 记录。"""
    orphan_ids = db.query(Tag.id).filter(
        ~db.query(item_tag_association.c.item_id)
        .filter(item_tag_association.c.tag_id == Tag.id)
        .exists()
    )
    db.query(Tag).filter(Tag.id.in_(orphan_ids)).delete(synchronize_session=False)
    db.commit()


def get_ingestion_status(item_id: int, db: Optional[Session] = None) -> Optional[dict]:
    """返回条目入库状态统计。"""
    db = db or SessionLocal()
    item = db.get(Item, item_id)
    if item is None:
        return None
    return {
        "item_id": item.id,
        "title": item.title,
        "type": item.type,
        "chunks_count": len(item.chunks),
        "tags": [t.name for t in item.tags],
        "tags_count": len(item.tags),
        "embedded": item.type == "note" and len(item.chunks) > 0,
    }
