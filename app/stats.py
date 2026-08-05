"""数据分析 / Inspector 统计（供前端 Text & Vector Storage Inspector 面板）

统计口径：
- Total Characters：所有 note/external_ref 的 content 字符总数
- Token Estimate：估算（中文字符≈0.7 token/字，英文≈0.25 token/字母，粗略按
  chars/1.5 估算，中文为主场景）
- Vector DB Size：Chroma 持久化目录的磁盘占用
- Chunk Count：chunks 表总数
- Source Distribution：按来源类型分布（Markdown / TXT / PDF / Web Crawl / 其它）
- Top Files：按字符数排序的前 N 大文本条目
"""
import os
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Chunk, Item

# 来源类型推导：根据 source / type / 文件扩展名
SOURCE_LABELS = {
    "markdown": "Markdown",
    "txt": "TXT",
    "pdf": "PDF",
    "web": "Web Crawl",
    "other": "其他",
}


def _classify_source(item: Item) -> str:
    """把一个 Item 归类到展示用来源类型。"""
    if item.source and item.source != "local":
        return "web"  # 外部收藏视为 Web Crawl
    if item.type == "external_ref":
        return "web"
    name = (item.title or "").lower()
    if name.endswith(".md") or name.endswith(".markdown"):
        return "markdown"
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith(".txt"):
        return "txt"
    # 无扩展名笔记默认 Markdown（个人库主要场景）
    if item.type == "note":
        return "markdown"
    return "other"


def _estimate_tokens(text: str) -> int:
    """粗略 token 估算：中文为主场景约 0.7 token/字；保守取 chars/1.4。"""
    return max(0, int(len(text) / 1.4))


def _dir_size(path: str) -> int:
    """递归统计目录字节数。"""
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def get_stats(db: Optional[Session] = None) -> dict:
    """返回 Inspector 面板所需的全部统计。"""
    db = db or SessionLocal()
    try:
        items = db.query(Item).all()
        total_chars = 0
        total_tokens = 0
        source_dist: Dict[str, int] = {"markdown": 0, "txt": 0, "pdf": 0, "web": 0, "other": 0}

        for it in items:
            if it.content:
                total_chars += len(it.content)
                total_tokens += _estimate_tokens(it.content)
            cls = _classify_source(it)
            source_dist[cls] = source_dist.get(cls, 0) + 1

        chunk_count = db.query(func.count(Chunk.id)).scalar() or 0

        # 向量库大小（Chroma 持久化目录）
        vector_size = _dir_size(settings.chroma_persist_directory)

        # Top N 大文本文件（note/external_ref，按字符数）
        text_items = [it for it in items if it.content]
        text_items.sort(key=lambda i: len(i.content or ""), reverse=True)
        top_files = [
            {
                "title": it.title,
                "chars": len(it.content or ""),
                "tokens": _estimate_tokens(it.content or ""),
                "type": it.type,
                "source": it.source,
            }
            for it in text_items[:10]
        ]

        # 格式化来源分布（带标签）
        distribution = [
            {"key": k, "label": SOURCE_LABELS[k], "count": source_dist.get(k, 0)}
            for k in ("markdown", "pdf", "web", "txt", "other")
        ]

        return {
            "total_chars": total_chars,
            "total_tokens": total_tokens,
            "vector_db_size": vector_size,
            "chunk_count": chunk_count,
            "item_count": len(items),
            "distribution": distribution,
            "top_files": top_files,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
    finally:
        db.close()
