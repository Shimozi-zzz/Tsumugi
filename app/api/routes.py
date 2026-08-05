"""API 路由 - 资料管理、检索、RAG 问答（含 SSE 流式）"""
import json
import os
import uuid
from typing import List, Optional

from fastapi import (
    APIRouter, Depends, HTTPException, UploadFile, File, Form, Query,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import ingest, rag, retrieval, stats
from app.connectors import persistence as connector_persistence
from app.connectors import registry as connector_registry
from app.database import get_db
from app.embeddings import EmbeddingError
from app.models import Item, Tag, item_tag_association
from app.schemas import (
    DeclarativeConnectorConfig,
    ExternalResult,
    FederatedSearchResponse,
    IngestResponse,
    ItemCreate,
    ItemListResponse,
    ItemOut,
    QueryRequest,
    RAGResponse,
    RetrievedChunk,
    SaveExternalRequest,
    SearchResponse,
    TagMerge,
    TagOut,
    TagRename,
)
from app.config import settings

router = APIRouter()

TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


def _item_out(item: Item) -> ItemOut:
    return ItemOut(
        id=item.id,
        title=item.title,
        type=item.type,
        content=item.content,
        file_path=item.file_path,
        image_url=item.image_url,
        source=item.source,
        external_id=item.external_id,
        synced_at=item.synced_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
        tags=[t.name for t in item.tags],
        chunks_count=len(item.chunks),
    )


def _split_tags(raw: Optional[str]) -> Optional[List[str]]:
    if not raw:
        return None
    return [t.strip() for t in raw.split(",") if t.strip()]


def _ingest_response(item: Item, duplicated: bool = False) -> IngestResponse:
    return IngestResponse(
        item_id=item.id,
        title=item.title,
        type=item.type,
        chunks_count=len(item.chunks),
        tags=[t.name for t in item.tags],
        duplicated=duplicated,
    )


def _ingest_sync(
    item_type: str,
    title: str,
    content: Optional[str],
    file_path: Optional[str],
    raw_bytes: Optional[bytes],
    ext: Optional[str],
    tag_names: Optional[List[str]],
    force: bool,
) -> IngestResponse:
    """在子线程中执行入库（自建并关闭 session），供 run_in_threadpool 调用。

    - note：内容判重 → ingest_text_document
    - image：上传场景（raw_bytes 非空）先保存文件，JSON 场景用已有 file_path；
      内容判重命中时提前返回，不写重复文件。
    返回已构造好的 IngestResponse（session 在返回前保持打开，避免懒加载报错）。
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        if item_type == "note":
            if not content or not content.strip():
                raise HTTPException(status_code=400, detail="上传的文本文件内容为空")
            if not force:
                existing = ingest.find_existing_by_hash(
                    db, ingest.compute_content_hash(content)
                )
                if existing is not None:
                    return _ingest_response(existing, duplicated=True)
            obj = ingest.ingest_text_document(
                title=title, content=content, tag_names=tag_names, db=db, force=force,
            )
            return _ingest_response(obj)

        # image 分支
        if raw_bytes is not None:  # 上传场景：保存附件
            if not force:
                existing = ingest.find_existing_by_hash(
                    db, ingest.compute_bytes_hash(raw_bytes)
                )
                if existing is not None:
                    return _ingest_response(existing, duplicated=True)  # 不写重复文件
            os.makedirs(settings.upload_dir, exist_ok=True)
            saved_name = f"{uuid.uuid4().hex}{ext}"
            file_path = os.path.join(settings.upload_dir, saved_name)
            with open(file_path, "wb") as f:
                f.write(raw_bytes)
        else:  # JSON 创建：file_path 已存在于磁盘
            if not file_path:
                raise HTTPException(status_code=400, detail="image 类型需要提供 file_path")
            if not force:
                existing = ingest.find_existing_by_hash(
                    db, ingest.compute_file_hash(file_path)
                )
                if existing is not None:
                    return _ingest_response(existing, duplicated=True)
        obj = ingest.ingest_image(
            title=title, file_path=file_path, tag_names=tag_names, db=db, force=force,
        )
        return _ingest_response(obj)
    finally:
        db.close()


def _sse(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


# ========== 资料管理 ==========

@router.post("/items", response_model=IngestResponse)
async def create_item(item: ItemCreate):
    """JSON 创建条目（note/image）。默认内容去重，force=True 强制再导入。
    入库为同步阻塞（embedding + Chroma 写入），移入线程池避免阻塞事件循环。"""
    if item.type not in ("note", "image"):
        raise HTTPException(status_code=400, detail="type 必须为 note 或 image")
    if item.type == "note" and not item.content:
        raise HTTPException(status_code=400, detail="note 类型需要提供 content")
    try:
        resp = await run_in_threadpool(
            _ingest_sync,
            item.type, item.title,
            item.content if item.type == "note" else None,
            item.file_path if item.type == "image" else None,
            None, None, item.tag_names, item.force,
        )
        return resp
    except EmbeddingError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"入库失败：{e}")


@router.post("/items/upload", response_model=IngestResponse)
async def upload_item(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    force: bool = Form(False),
):
    """上传文件导入。.md/.txt 按文本切分入库；图片存为附件（仅路径+元数据）。
    默认内容去重（force=true 时强制再导入）。文件读取为 async，解码/入库
    放线程池。"""
    filename = file.filename or "untitled"
    ext = os.path.splitext(filename)[1].lower()
    doc_title = (title or "").strip() or os.path.splitext(os.path.basename(filename))[0]
    tag_names = _split_tags(tags)

    try:
        raw = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"读取上传文件失败：{e}")

    try:
        if ext in TEXT_EXTENSIONS:
            # 大文本 decode 可能耗时，一并放线程池
            def _work():
                try:
                    content = raw.decode("utf-8")
                except UnicodeDecodeError:
                    content = raw.decode("utf-8", errors="replace")
                return _ingest_sync(
                    "note", doc_title, content, None, None, None, tag_names, force,
                )

            resp = await run_in_threadpool(_work)
        elif ext in IMAGE_EXTENSIONS:
            resp = await run_in_threadpool(
                _ingest_sync, "image", doc_title, None, None, raw, ext, tag_names, force,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型 {ext}，支持：{sorted(TEXT_EXTENSIONS | IMAGE_EXTENSIONS)}",
            )
        return resp
    except EmbeddingError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"入库失败：{e}")


@router.get("/items", response_model=ItemListResponse)
async def list_items(
    skip: int = Query(0),
    limit: int = Query(50),
    tag: Optional[List[str]] = Query(None),
    tag_match: str = Query("any"),
    type: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """列出资料条目（分页 + 结构化筛选）。

    - tag：可传多次（?tag=a&tag=b），默认任意命中，tag_match=all 为全部命中
    - type / source：精确匹配
    返回 {total, items}，total 为**筛选后**总数（不受分页影响）。
    """
    query = db.query(Item)

    if tag:
        tag_rows = (
            db.query(Item.id)
            .join(item_tag_association, Item.id == item_tag_association.c.item_id)
            .join(Tag, Tag.id == item_tag_association.c.tag_id)
            .filter(Tag.name.in_(tag))
            .group_by(Item.id)
            .having(
                func.count(func.distinct(Tag.id)) >= len(tag)
                if tag_match == "all"
                else func.count(Tag.id) >= 1
            )
            .subquery()
        )
        query = query.join(tag_rows, Item.id == tag_rows.c.id)

    if type:
        query = query.filter(Item.type == type)
    if source:
        query = query.filter(Item.source == source)

    total = query.count()
    items = query.order_by(Item.id.desc()).offset(skip).limit(limit).all()
    return ItemListResponse(total=total, items=[_item_out(i) for i in items])


@router.get("/items/{item_id}", response_model=ItemOut)
async def get_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return _item_out(item)


@router.get("/items/{item_id}/status")
async def item_status(item_id: int, db: Session = Depends(get_db)):
    status = ingest.get_ingestion_status(item_id, db=db)
    if status is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return status


@router.delete("/items/{item_id}")
async def delete_item(item_id: int, db: Session = Depends(get_db)):
    ok = ingest.delete_item(item_id, db=db)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"deleted": item_id}


@router.post("/items/{item_id}/cover", response_model=ItemOut)
async def upload_item_cover(
    item_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """为资料条目设置自定义封面图（存 thumbnails 目录，更新 image_url）。"""
    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    ext = os.path.splitext(file.filename or "cover.jpg")[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的图片类型 {ext}")
    try:
        raw = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"读取上传图片失败：{e}")

    os.makedirs(settings.thumbnails_dir, exist_ok=True)
    saved_name = f"cover_{item_id}_{uuid.uuid4().hex}{ext}"
    saved_path = os.path.join(settings.thumbnails_dir, saved_name)
    with open(saved_path, "wb") as f:
        f.write(raw)

    # 更新封面：本地路径存 file_path，image_url 存可访问的 /static URL
    item.file_path = saved_path
    item.image_url = f"/static/thumbnails/{saved_name}"
    db.commit()
    db.refresh(item)
    return _item_out(item)


# ========== 标签 ==========

def _tag_out(tag: Tag) -> TagOut:
    return TagOut(id=tag.id, name=tag.name, count=len(tag.items))


@router.get("/tags", response_model=List[TagOut])
async def list_tags(db: Session = Depends(get_db)):
    tags = db.query(Tag).order_by(Tag.name).all()
    return [_tag_out(t) for t in tags]


@router.patch("/tags/{tag_id}", response_model=TagOut)
async def rename_tag(tag_id: int, body: TagRename, db: Session = Depends(get_db)):
    """重命名标签。新名称与已有标签冲突时返回 409。"""
    tag = db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    new_name = body.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="标签名不能为空")
    conflict = db.query(Tag).filter(Tag.name == new_name, Tag.id != tag_id).first()
    if conflict:
        raise HTTPException(status_code=409, detail=f"标签名 '{new_name}' 已存在")
    tag.name = new_name
    db.commit()
    db.refresh(tag)
    return _tag_out(tag)


@router.delete("/tags/{tag_id}")
async def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    """删除标签（解除所有关联，不删除条目）。"""
    tag = db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    db.query(item_tag_association).filter(item_tag_association.c.tag_id == tag_id).delete(
        synchronize_session=False
    )
    db.delete(tag)
    db.commit()
    return {"deleted": tag_id}


@router.post("/tags/merge", response_model=TagOut)
async def merge_tags(body: TagMerge, db: Session = Depends(get_db)):
    """合并标签：source_tag_ids 全部并入 target_tag_id 后删除前者。
    目标标签的关联去重。"""
    target = db.get(Tag, body.target_tag_id)
    if not target:
        raise HTTPException(status_code=404, detail=f"目标标签 {body.target_tag_id} 不存在")

    target_item_ids = {
        r[0]
        for r in db.query(item_tag_association.c.item_id)
        .filter(item_tag_association.c.tag_id == target.id)
        .all()
    }

    for sid in body.source_tag_ids:
        if sid == target.id:
            continue
        src = db.get(Tag, sid)
        if not src:
            raise HTTPException(status_code=404, detail=f"源标签 {sid} 不存在")
        for (item_id,) in (
            db.query(item_tag_association.c.item_id)
            .filter(item_tag_association.c.tag_id == sid)
            .all()
        ):
            if item_id not in target_item_ids:
                db.execute(
                    item_tag_association.insert().values(item_id=item_id, tag_id=target.id)
                )
                target_item_ids.add(item_id)
        # 解除源标签关联并删除
        db.query(item_tag_association).filter(
            item_tag_association.c.tag_id == sid
        ).delete(synchronize_session=False)
        db.delete(src)

    db.commit()
    db.refresh(target)
    return _tag_out(target)


# ========== 数据分析 / Inspector ==========

@router.get("/stats")
async def get_stats():
    """Text & Vector Storage Inspector 统计（字符数/token/向量库大小/
    chunk 数/来源分布/Top 文件）。"""
    try:
        data = await run_in_threadpool(stats.get_stats)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"统计失败：{e}")


# ========== 检索 ==========

@router.post("/search", response_model=SearchResponse)
async def search_chunks(q: QueryRequest):
    try:
        # 检索为同步阻塞（embedding + Chroma 查询），移入线程池避免阻塞事件循环
        results = await run_in_threadpool(
            retrieval.retrieve_chunks,
            query=q.query,
            top_k=q.top_k or settings.top_k,
            tags=q.tag_filter,
            max_chunks_per_item=q.max_chunks_per_item,
            tag_match=q.tag_match,
        )
    except EmbeddingError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检索失败：{e}")
    return SearchResponse(results=results)


# ========== Connector 联合检索 / 收藏入库（Phase 3） ==========

def _search_result_to_external(sr) -> ExternalResult:
    return ExternalResult(
        source=sr.source,
        title=sr.title,
        subtitle=sr.subtitle,
        description=sr.description,
        image_url=sr.image_url,
        external_id=sr.external_id,
        rating=sr.rating,
        tags=sr.tags,
        raw=sr.raw,
    )


def _federated_search_sync(query: str, local_top_k: int, tag_filter, tag_match):
    """在子线程中执行：本地检索 + 各已启用 Connector 的实时检索。

    单个数据源失败只记录该源错误，不阻塞其它源与本地检索结果返回
    （错误信息通过 err 透出，前端可提示"某源暂不可用"）。"""
    from app.connectors.base import ConnectorError, RateLimitError

    local_results = []
    try:
        local_results = retrieval.retrieve_chunks(
            query=query, top_k=local_top_k,
            tags=tag_filter, tag_match=tag_match,
        )
    except EmbeddingError:
        local_results = []  # 本地检索失败不阻塞外部检索

    external = []
    errors = {}
    for connector in connector_registry.get_enabled_connectors():
        try:
            hits = connector.search(query)
            external.extend(_search_result_to_external(h) for h in hits)
        except RateLimitError as e:
            errors[connector.name] = f"限流：{e}"
        except ConnectorError as e:
            errors[connector.name] = str(e)
        except Exception as e:  # 兜底：单个源异常不影响整体
            errors[connector.name] = f"未知错误：{e}"
    return local_results, external, errors


@router.post("/search/federated", response_model=FederatedSearchResponse)
async def federated_search(q: QueryRequest):
    """联合检索：本地向量检索 + 已启用 Connector 的实时/缓存检索结果合并。
    结果按来源分组返回（前端用角标区分）；单源失败降级，不阻塞其它源。"""
    try:
        local_results, external, errors = await run_in_threadpool(
            _federated_search_sync,
            q.query, q.top_k or settings.top_k, q.tag_filter, q.tag_match,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"联合检索失败：{e}")
    return FederatedSearchResponse(
        query=q.query, results=external, local_results=local_results,
        errors=errors,
    )


@router.get("/connectors")
async def list_connectors():
    """列出已注册/启用的数据源。"""
    manifests = connector_registry.list_manifests()
    return [
        {
            "name": m.name,
            "display_name": m.display_name,
            "version": m.version,
            "capabilities": m.capabilities,
            "enabled": connector_registry.is_enabled(m.name),
        }
        for m in manifests
    ]


@router.post("/connectors")
async def create_declarative_connector(cfg: DeclarativeConnectorConfig):
    """创建声明式自定义数据源（Phase 4）。

    用户提供 HTTP 端点 + 字段映射即可接入，不执行任意代码。
    配置保存到 sources 表，并立即注册启用。
    """
    config = cfg.model_dump()
    try:
        connector_registry.register_declarative(config, enabled=True)
        connector_persistence.save_declarative_config(config, enabled=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建数据源失败：{e}")
    return {
        "name": cfg.name,
        "display_name": cfg.display_name or cfg.name,
        "enabled": True,
    }


@router.delete("/connectors/{name}")
async def delete_declarative_connector(name: str):
    """删除声明式数据源（同时解除注册与持久化配置）。"""
    connector_registry.unregister(name)
    connector_persistence.delete_declarative_config(name)
    return {"deleted": name}


def _save_external_sync(req: SaveExternalRequest) -> IngestResponse:
    """在子线程中执行收藏入库。外部封面图缓存到本地（失败不阻塞）。"""
    from app.database import SessionLocal
    from app.images import cache_external_image

    local_thumb = cache_external_image(req.image_url)
    db = SessionLocal()
    try:
        obj = ingest.ingest_external(
            source=req.source,
            external_id=req.external_id,
            title=req.title,
            content=req.description or "",
            image_url=req.image_url,
            tags=req.tags,
            db=db,
        )
        # 本地缩略图路径存到 file_path（与 image_url 区分：本地 vs 外部）
        if local_thumb and not obj.file_path:
            obj.file_path = local_thumb
            db.commit()
            db.refresh(obj)
        return _ingest_response(obj)
    finally:
        db.close()


@router.post("/items/save-external", response_model=IngestResponse)
async def save_external(req: SaveExternalRequest):
    """收藏入库（Save to Library）：把外部搜索结果存为本地条目。
    同一 source+external_id 重复收藏幂等（返回已有条目）。"""
    if req.source == "local":
        raise HTTPException(status_code=400, detail="source 不能为 local")
    try:
        return await run_in_threadpool(_save_external_sync, req)
    except EmbeddingError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"收藏入库失败：{e}")


# ========== RAG 问答 ==========

@router.post("/rag/query", response_model=RAGResponse)
async def rag_query(q: QueryRequest):
    try:
        chunks = await run_in_threadpool(
            retrieval.retrieve_chunks,
            query=q.query, top_k=q.top_k or settings.top_k, tags=q.tag_filter,
            tag_match=q.tag_match,
        )
        if not chunks:
            return RAGResponse(
                answer="知识库中没有检索到与问题相关的资料。",
                retrieved_chunks=[],
            )
        answer = await rag.generate_answer_non_stream(q.query, chunks)
    except EmbeddingError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except rag.LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成回答失败：{e}")
    return RAGResponse(answer=answer, retrieved_chunks=chunks)


@router.post("/rag/query/stream")
async def rag_query_stream(q: QueryRequest):
    """RAG 流式问答（SSE）。事件：
    sources / chunk / done / error，均为 data: {json}。"""
    try:
        chunks = await run_in_threadpool(
            retrieval.retrieve_chunks,
            query=q.query, top_k=q.top_k or settings.top_k, tags=q.tag_filter,
            tag_match=q.tag_match,
        )
    except EmbeddingError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检索失败：{e}")

    sources = [
        RetrievedChunk(
            content=c.content, item_title=c.item_title,
            item_id=c.item_id, score=c.score, tags=c.tags,
        )
        for c in chunks
    ]

    async def event_stream():
        yield _sse({"type": "sources", "sources": [s.model_dump() for s in sources]})
        if not chunks:
            yield _sse({"type": "done", "answer": "", "sources": []})
            return
        try:
            pieces: List[str] = []
            async for piece in rag.generate_answer(q.query, chunks, stream=True):
                pieces.append(piece)
                yield _sse({"type": "chunk", "content": piece})
            yield _sse({"type": "done", "answer": "".join(pieces),
                        "sources": [s.model_dump() for s in sources]})
        except rag.LLMError as e:
            yield _sse({"type": "error", "message": str(e)})
        except Exception as e:
            yield _sse({"type": "error", "message": f"生成回答失败：{e}"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
