"""API 路由 - 资料管理、检索、RAG 问答（含 SSE 流式）"""
import json
import os
import re
import uuid
from typing import List, Optional

from fastapi import (
    APIRouter, Depends, HTTPException, UploadFile, File, Form, Query,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app import characters, collections, ingest, memories, provider_store, providers, rag, retrieval, reviews, stats, work_model
from app.connectors import persistence as connector_persistence
from app.connectors import registry as connector_registry
from app.connectors.base import ConnectorError, validate_proxy_url
from app.database import get_db
from app.embeddings import EmbeddingError
from app.models import Character, Collection, Item, Media, Memory, Review, Tag, item_tag_association
from app.schemas import (
    BangumiAuthorizeOut,
    BangumiImportStartOut,
    BangumiImportStatusOut,
    BangumiOAuthConfig,
    BangumiOAuthStatusOut,
    BatchDeleteRequest,
    BatchTagsRequest,
    CharacterOut,
    CharactersResponse,
    DeclarativeConnectorConfig,
    ConnectorProxyRequest,
    ExternalDetailOut,
    ExternalResult,
    FederatedSearchResponse,
    IngestResponse,
    ItemCreate,
    ItemDetailOut,
    ItemListResponse,
    ItemOut,
    ItemTagsRequest,
    LLMProviderCreate,
    LLMProviderList,
    LLMProviderOut,
    LLMTestRequest,
    LLMTestResponse,
    MemoryOut,
    QueryRequest,
    RAGResponse,
    RelatedSourceOut,
    RetrievedChunk,
    PluginsResponse,
    ReviewCreate,
    ReviewOut,
    ReviewUpdate,
    SaveExternalRequest,
    SearchResponse,
    TagMerge,
    TagOut,
    TagRename,
    CollectionUpdate,
    WorkUpdate,
)
from app.config import settings

router = APIRouter()

TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


def _strip_text_ext(filename: str) -> str:
    """剥掉文件名末尾的已知文本扩展名链，作为文档标题。

    例：`notes.txt.md` → `notes`（先剥 .md 再剥 .txt）；`a.txt` → `a`。
    """
    stem = os.path.basename(filename)
    while True:
        base, ext = os.path.splitext(stem)
        if base and ext.lower() in TEXT_EXTENSIONS:
            stem = base
        else:
            break
    return stem


def _item_out(item: Item) -> ItemOut:
    col = item.collection
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
        work_type=item.work_type,
        alternative_title=item.alternative_title,
        release_date=item.release_date,
        collection_status=col.status if col else None,
        collected_at=col.added_at if col else None,
        favorite=bool(col.favorite) if col else False,
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
    doc_title = (title or "").strip() or _strip_text_ext(filename)
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
    work_type: Optional[str] = Query(None),
    collection_status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """列出资料条目（分页 + 结构化筛选）。

    - tag：可传多次（?tag=a&tag=b），默认任意命中，tag_match=all 为全部命中
    - type / source / work_type：精确匹配（work_type 为 P1 世界轴列）
    - collection_status：追番状态筛选（P2 收藏关系）
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
    if work_type:
        query = query.filter(Item.work_type == work_type)
    if collection_status:
        query = query.join(Collection, Collection.item_id == Item.id) \
            .filter(Collection.status == collection_status)

    total = query.count()
    query = query.options(selectinload(Item.collection))  # 避免列表 N+1
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


def _batch_tags_sync(body: BatchTagsRequest) -> int:
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        updated = 0
        for iid in body.item_ids:
            try:
                ingest.set_item_tags(iid, body.tag_names, body.mode, db=db)
                updated += 1
            except ValueError:
                continue
        return updated
    finally:
        db.close()


# 注意：/items/batch/... 必须在 /items/{item_id}/... 之前声明，
# 否则 "batch" 会被 {item_id} 捕获。
@router.post("/items/batch/tags")
async def batch_item_tags(body: BatchTagsRequest):
    """批量打标签（对选中的条目）。mode: add/remove/set。"""
    if not body.item_ids:
        return {"updated": 0, "requested": 0}
    updated = await run_in_threadpool(_batch_tags_sync, body)
    return {"updated": updated, "requested": len(body.item_ids)}


@router.post("/items/batch/delete")
async def batch_delete_items(body: BatchDeleteRequest):
    """批量删除条目（前端需二次确认）。"""
    if not body.item_ids:
        return {"deleted": 0}
    deleted = await run_in_threadpool(ingest.delete_items, body.item_ids)
    return {"deleted": deleted}


@router.post("/items/{item_id}/tags", response_model=ItemOut)
async def update_item_tags(item_id: int, body: ItemTagsRequest, db: Session = Depends(get_db)):
    """给单个条目增/删/设置标签（右键菜单"编辑标签"用）。"""
    try:
        await run_in_threadpool(
            ingest.set_item_tags, item_id, body.tag_names, body.mode,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    fresh = db.get(Item, item_id)
    if fresh is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return _item_out(fresh)


@router.patch("/items/{item_id}/work", response_model=ItemOut)
async def update_work_columns(item_id: int, body: WorkUpdate, db: Session = Depends(get_db)):
    """手动编辑作品档案世界轴列（P1 / ADR 0045）：work_type/原名/发行。

    - work_type 必须属于枚举（anime/manga/game/galgame/novel/other），
      传空字符串表示清除（设为 None）；
    - alternative_title / release_date 传空字符串同样表示清除；
    - 用户手动改过的值，启动回填不会覆盖（回填只在 NULL 时写）。
    """
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    def _set(field: str, value):
        if value is None:
            return
        setattr(item, field, value.strip() if value.strip() else None)

    if body.work_type is not None:
        wt = body.work_type.strip()
        if wt and wt not in work_model.WORK_TYPES:
            raise HTTPException(status_code=400, detail=f"work_type 必须是 {work_model.WORK_TYPES} 之一")
        item.work_type = wt or None
    _set("alternative_title", body.alternative_title)
    _set("release_date", body.release_date)
    db.commit()
    db.refresh(item)
    return _item_out(item)


@router.patch("/items/{item_id}/collection", response_model=ItemOut)
async def update_collection(item_id: int, body: CollectionUpdate, db: Session = Depends(get_db)):
    """手动编辑收藏关系（P2 / ADR 0046）：追番状态 / 是否喜欢。

    status 必须在枚举内（想看/在看/看完/搁置/弃坑），空串=清除；favorite 布尔。
    """
    try:
        await run_in_threadpool(collections.set_collection, item_id, db=db,
                                status=body.status, favorite=(1 if body.favorite else 0) if body.favorite is not None else None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    fresh = db.get(Item, item_id)
    if fresh is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return _item_out(fresh)


@router.get("/collections")
async def list_collections(db: Session = Depends(get_db)):
    """全部收藏关系（{item_id → status}，前端状态分组列表 statusMap 用，P2）。"""
    rows = db.query(Collection.item_id, Collection.status).all()
    return [{"item_id": i, "status": s} for i, s in rows]


# ========== Bangumi OAuth + 批量导入 ==========

def _bangumi_redirect_uri() -> str:
    return f"http://127.0.0.1:{settings.tsumugi_port}/api/bangumi/oauth/callback"


@router.get("/bangumi/oauth/status", response_model=BangumiOAuthStatusOut)
async def bangumi_oauth_status():
    """连接状态（不返回任何令牌明文）。"""
    from app import bangumi_oauth
    tokens = bangumi_oauth.get_tokens() or {}
    uid = tokens.get("user_id")
    return BangumiOAuthStatusOut(
        connected=bangumi_oauth.is_connected(),
        config_configured=bangumi_oauth.is_config_configured(),
        user_id=str(uid) if uid is not None else None,
        expires_at=tokens.get("expires_at"),
        redirect_uri=_bangumi_redirect_uri(),
    )


@router.post("/bangumi/oauth/config")
async def bangumi_oauth_config(body: BangumiOAuthConfig):
    """保存 Bangumi 应用凭证（client_id/secret 写入 .env，不落库明文）。"""
    from app import bangumi_oauth
    try:
        bangumi_oauth.save_client_config(body.client_id, body.client_secret)
    except bangumi_oauth.OAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.get("/bangumi/oauth/authorize-url", response_model=BangumiAuthorizeOut)
async def bangumi_oauth_authorize():
    """生成跳转 Bangumi 授权页的 URL（前端 window.open）。"""
    from app import bangumi_oauth
    try:
        url = bangumi_oauth.build_authorize_url(_bangumi_redirect_uri())
    except bangumi_oauth.OAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return BangumiAuthorizeOut(authorize_url=url, redirect_uri=_bangumi_redirect_uri())


@router.get("/bangumi/oauth/callback")
async def bangumi_oauth_callback(code: str, state: Optional[str] = None):
    """Bangumi 授权回调：code 换 token。返回可展示的 HTML 提示关闭页面。"""
    from app import bangumi_oauth
    try:
        bangumi_oauth.exchange_code(code, _bangumi_redirect_uri(), state=state)
    except bangumi_oauth.OAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;padding:2rem;background:#fafafa;color:#18181b'>"
        "<h2>Bangumi 授权成功 ✓</h2><p>可以关闭此页面，回到 Tsumugi 继续导入。</p></body></html>"
    )


@router.post("/bangumi/oauth/refresh")
async def bangumi_oauth_refresh():
    """手动刷新令牌（通常在 token 临近过期时由 get_valid_access_token 自动触发）。"""
    from app import bangumi_oauth
    try:
        bangumi_oauth.refresh_access_token()
    except bangumi_oauth.NeedsReauthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return {"ok": True}


@router.post("/bangumi/oauth/disconnect")
async def bangumi_oauth_disconnect():
    from app import bangumi_oauth
    bangumi_oauth.disconnect()
    return {"ok": True}


@router.post("/bangumi/import", response_model=BangumiImportStartOut)
async def bangumi_import_start():
    """启动批量导入（后台线程，进度轮询 /bangumi/import/status）。"""
    from app import bangumi_import, bangumi_oauth
    try:
        token = bangumi_oauth.get_valid_access_token()
    except bangumi_oauth.NeedsReauthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    job_id = bangumi_import.start_import(token)
    return BangumiImportStartOut(job_id=job_id)


@router.get("/bangumi/import/status", response_model=BangumiImportStatusOut)
async def bangumi_import_status(job_id: str):
    from app import bangumi_import
    job = bangumi_import.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="import job not found")
    return BangumiImportStatusOut(job_id=job_id, **job)


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


# ========== Review 读后感/书评 ==========

def _review_out(review: Review, db: Session) -> ReviewOut:
    item = db.get(Item, review.item_id)  # 显式加载，避免 DetachedInstanceError
    return ReviewOut(
        id=review.id,
        item_id=review.item_id,
        item_title=item.title if item else "",
        title=review.title,
        content=review.content,
        rating=review.rating,
        status=review.status,
        spoiler=bool(review.spoiler),
        font_size=review.font_size,
        public_rating=reviews.get_public_rating(item) if item else None,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


@router.post("/items/{item_id}/reviews", response_model=ReviewOut)
async def create_review(item_id: int, body: ReviewCreate, db: Session = Depends(get_db)):
    """创建一条 review（内容参与 RAG 检索）。"""
    try:
        review = await run_in_threadpool(
            reviews.create_review,
            item_id=item_id,
            content=body.content,
            title=body.title,
            rating=body.rating,
            status=body.status,
            spoiler=body.spoiler,
            font_size=body.font_size,
        )
        return _review_out(review, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except EmbeddingError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建 review 失败：{e}")


@router.get("/items/{item_id}/reviews", response_model=List[ReviewOut])
async def list_reviews(item_id: int, db: Session = Depends(get_db)):
    """某 item 的全部 review（时间倒序）。"""
    if db.get(Item, item_id) is None:
        raise HTTPException(status_code=404, detail="Item not found")
    rows = reviews.list_reviews(item_id, db=db)
    return [_review_out(r, db) for r in rows]


@router.patch("/reviews/{review_id}", response_model=ReviewOut)
async def update_review(review_id: int, body: ReviewUpdate, db: Session = Depends(get_db)):
    """编辑 review（内容变化时同步更新向量）。"""
    try:
        review = await run_in_threadpool(
            reviews.update_review,
            review_id=review_id,
            content=body.content,
            title=body.title,
            rating=body.rating,
            status=body.status,
            spoiler=body.spoiler,
            font_size=body.font_size,
        )
        return _review_out(review, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except EmbeddingError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新 review 失败：{e}")


@router.delete("/reviews/{review_id}")
async def delete_review(review_id: int):
    """删除 review（含向量清理）。"""
    ok = reviews.delete_review(review_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Review not found")
    return {"deleted": review_id}


@router.get("/reviews", response_model=List[ReviewOut])
async def list_all_reviews(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """全局 review 列表（最近写的，时间倒序）。"""
    rows = db.query(Review).order_by(Review.created_at.desc()) \
        .offset(skip).limit(limit).all()
    return [_review_out(r, db) for r in rows]


# ========== Memory 记忆（Phase A，ADR 0041） ==========

def _memory_out(mem: Memory, db: Session) -> MemoryOut:
    item = db.get(Item, mem.item_id)  # 显式加载，避免 DetachedInstanceError
    return MemoryOut(
        id=mem.id,
        item_id=mem.item_id,
        item_title=item.title if item else "",
        source_type=mem.source_type,
        source_ref=mem.source_ref,
        occurred_at=mem.occurred_at,
        summary=mem.summary,
        emotion=mem.emotion,
        media=[{"id": m.id, "url": _media_url(m.file_path), "media_type": m.media_type} for m in mem.media],
        created_at=mem.created_at,
    )


def _media_url(file_path: Optional[str]) -> str:
    """本地附件路径（./data/uploads/x）→ 可访问 URL（/static/uploads/x）。"""
    if not file_path:
        return ""
    return file_path.replace("\\", "/").replace("./data/", "/static/")


@router.get("/items/{item_id}/memories", response_model=List[MemoryOut])
async def list_item_memories(item_id: int, db: Session = Depends(get_db)):
    """某作品的全部记忆（按发生时间倒序）。Phase B 作品记忆时间轴用。"""
    if db.get(Item, item_id) is None:
        raise HTTPException(status_code=404, detail="Item not found")
    rows = memories.list_item_memories(item_id, db=db)
    return [_memory_out(m, db) for m in rows]


@router.get("/memories", response_model=List[MemoryOut])
async def list_memories(
    item_id: Optional[int] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    month: Optional[int] = None,
    day: Optional[int] = None,
    max_year: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """全局记忆查询（Phase C 记忆回廊）：按时间范围 / item 筛选。

    start/end 支持 ISO 时间或纯日期（如 2023，作 end 时按当日结束处理）。
    传 month+day 时切换为"跨年同月同日"查询（Phase E 往年今日）：
    命中历史任意年份同月同日的记忆，max_year 过滤掉当年（默认传今年）。
    """
    if month is not None and day is not None:
        rows = memories.query_on_this_day(
            db, month=month, day=day, max_year=max_year, limit=limit,
        )
    else:
        rows = memories.query_memories(
            db, item_id=item_id, start=start, end=end, skip=skip, limit=limit,
        )
    return [_memory_out(m, db) for m in rows]


@router.post("/items/{item_id}/memories", response_model=MemoryOut)
async def create_memory(
    item_id: int,
    summary: str = Form(...),
    source_type: str = Form("text"),
    emotion: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """创建直接 Memory（P3 / ADR 0047）：轻量文字 / 里程碑 + 可选情绪 + 可选附图。

    multipart/form-data：summary 必填；source_type ∈ text/milestone；
    emotion 可选（前端固定小集）；file 可选（截图/插图，存 data/uploads）。
    """
    if db.get(Item, item_id) is None:
        raise HTTPException(status_code=404, detail="Item not found")
    try:
        mem = await run_in_threadpool(
            memories.create_direct_memory,
            item_id=item_id, summary=summary, source_type=source_type,
            emotion=emotion or None, db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if file is not None and file.filename:
        raw = await file.read()
        ext = os.path.splitext(file.filename)[1] or ".png"
        os.makedirs(settings.upload_dir, exist_ok=True)
        saved = f"{uuid.uuid4().hex}{ext}"
        with open(os.path.join(settings.upload_dir, saved), "wb") as f:
            f.write(raw)
        m = Media(item_id=item_id, memory_id=mem.id,
                  file_path=f"./data/uploads/{saved}", media_type="image", size=len(raw))
        db.add(m)
        db.commit()
        db.refresh(mem)
    return _memory_out(mem, db)


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int):
    """删除直接创建的 Memory（text/milestone，含其媒体附件级联；review/collection 不允许）。"""
    ok = memories.delete_direct_memory(memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found 或不允许删除")
    return {"deleted": memory_id}


# ========== LLM Provider 管理 ==========

def _provider_out(p: dict) -> LLMProviderOut:
    return LLMProviderOut(**p)


@router.get("/llm/providers", response_model=LLMProviderList)
async def list_llm_providers():
    """列出全部 provider 配置 + 当前启用名。"""
    providers_list = provider_store.list_providers()
    enabled = provider_store.get_enabled_provider()
    return LLMProviderList(
        providers=[_provider_out(p) for p in providers_list],
        enabled_name=enabled["name"] if enabled else None,
    )


@router.post("/llm/providers", response_model=LLMProviderOut)
async def save_llm_provider(body: LLMProviderCreate):
    """保存 provider 配置（name 唯一，存在则覆盖）。保存前做 SSRF 校验。

    api_key 两种方式（UI 可任选）：
    - 占位符 {ENV_VAR}：原样存 api_key_ref；
    - 真实 key（明文）：由后端写入 .env（生成 {TSUMUGI_API_KEY_*} 占位符引用
      存库），**不落数据库明文**（见 ADR 0017）。
    """
    if body.provider_type not in ("openai_compatible", "ollama"):
        raise HTTPException(status_code=400, detail="provider_type 必须是 openai_compatible 或 ollama")
    # 先分类 api_key 输入（畸形占位符拒绝）
    try:
        mode = providers.classify_api_key_ref(body.api_key_ref)
    except providers.ProviderError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # SSRF 配置期校验（resolve=False）：内网/回环地址拒绝（Ollama 放行 localhost）
    try:
        providers.provider_from_config(
            {"provider_type": body.provider_type, "base_url": body.base_url,
             "model_id": body.model_id, "api_key_ref": body.api_key_ref},
            validate=True,
        )
    except providers.ProviderError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # 明文 key → 落地 .env 换成占位符引用（不落库明文）
    stored_ref = body.api_key_ref
    if mode == "plaintext":
        try:
            stored_ref = providers.persist_api_key_placeholder(body.name, body.api_key_ref)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"写入 .env 失败：{e}")
    try:
        saved = provider_store.save_provider(
            name=body.name,
            provider_type=body.provider_type,
            base_url=body.base_url,
            model_id=body.model_id,
            api_key_ref=stored_ref,
            enabled=body.enabled,
        )
        return _provider_out(saved)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存 provider 失败：{e}")


@router.patch("/llm/providers/{name}/enable", response_model=LLMProviderOut)
async def enable_llm_provider(name: str, enabled: bool = True):
    """启用/停用 provider（启用时清其它）。"""
    saved = provider_store.set_enabled(name, enabled)
    if saved is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return _provider_out(saved)


@router.delete("/llm/providers/{name}")
async def delete_llm_provider(name: str):
    ok = provider_store.delete_provider(name)
    if not ok:
        raise HTTPException(status_code=404, detail="Provider not found")
    return {"deleted": name}


@router.post("/llm/test", response_model=LLMTestResponse)
async def test_llm_connection(body: LLMTestRequest):
    """测试连接：优先用已保存配置（name），否则用请求内临时配置。"""
    if body.name:
        cfg = provider_store.get_provider(body.name)
        if cfg is None:
            raise HTTPException(status_code=404, detail="Provider not found")
    else:
        if not body.base_url or not body.model_id:
            raise HTTPException(status_code=400, detail="测试连接需要 base_url 和 model_id")
        # 临时配置的 api_key：占位符原样引用；明文直接作为 api_key（不持久化）
        try:
            mode = providers.classify_api_key_ref(body.api_key_ref)
        except providers.ProviderError as e:
            raise HTTPException(status_code=400, detail=str(e))
        cfg = {
            "name": "test", "provider_type": body.provider_type or "openai_compatible",
            "base_url": body.base_url, "model_id": body.model_id,
        }
        if mode == "placeholder":
            cfg["api_key_ref"] = body.api_key_ref
        elif mode == "plaintext":
            cfg["api_key"] = body.api_key_ref.strip()
    try:
        message = await run_in_threadpool(providers.test_connection, cfg)
        return LLMTestResponse(ok=True, message=message)
    except providers.ProviderError as e:
        return LLMTestResponse(ok=False, message=str(e))
    except Exception as e:
        return LLMTestResponse(ok=False, message=f"测试连接失败：{e}")


@router.get("/llm/ollama-status")
async def ollama_status():
    """检测本机 Ollama 服务是否可访问（localhost:11434/v1/models）。"""
    import httpx
    try:
        resp = httpx.get("http://localhost:11434/v1/models", timeout=3.0)
        if resp.status_code == 200:
            data = resp.json()
            models = [m.get("id") for m in data.get("data", [])]
            return {"available": True, "models": models}
        return {"available": False, "models": [], "reason": f"HTTP {resp.status_code}"}
    except httpx.ConnectError:
        return {"available": False, "models": [], "reason": "无法连接 localhost:11434"}
    except httpx.TimeoutException:
        return {"available": False, "models": [], "reason": "连接超时"}
    except Exception as e:
        return {"available": False, "models": [], "reason": str(e)}


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


@router.get("/activity")
async def get_activity(year: Optional[int] = Query(None, ge=2000, le=2100),
                       db: Session = Depends(get_db)):
    """年度活跃度（ADR 0033）：按天聚合 书评数 + 收藏数（加权得分）。

    数据来源：Review.created_at（书评）+ 外部条目 Item.synced_at（新收藏）。
    返回当年有活跃记录的日期列表与统计摘要（总数/最活跃月份/最长连续活跃）。
    """
    from datetime import datetime as _dt
    y = year or _dt.now().year
    try:
        data = await run_in_threadpool(stats.get_activity_summary, db, y)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"年度统计失败：{e}")


# ========== 数据备份/导出/导入（ADR 0038） ==========

@router.get("/backup/export")
async def export_backup(db: Session = Depends(get_db)):
    """导出图书馆数据为单个 JSON 文档（含 items/reviews/tags/sources/llm_providers，
    不含明文密钥；向量库不导出，可从内容重建）。"""
    from app import backup
    try:
        return await run_in_threadpool(backup.export_backup, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败：{e}")


@router.post("/backup/import")
async def import_backup(body: dict):
    """导入备份 JSON（后台线程，幂等合并；进度轮询 status）。"""
    from app import backup
    try:
        job_id = backup.start_import(body)
        return {"job_id": job_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败：{e}")


@router.get("/backup/import/status/{job_id}")
async def import_status(job_id: str):
    from app import backup
    job = backup.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    return job


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
            source_types=q.source_types,
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


def _federated_search_sync(query: str, local_top_k: int, tag_filter, tag_match,
                           source_types):
    """在子线程中执行：本地检索 + 各已启用 Connector 的实时检索。

    单个数据源失败只记录该源错误，不阻塞其它源与本地检索结果返回
    （错误信息通过 err 透出，前端可提示"某源暂不可用"）。"""
    from app.connectors.base import ConnectorError, RateLimitError

    local_results = []
    try:
        local_results = retrieval.retrieve_chunks(
            query=query, top_k=local_top_k,
            tags=tag_filter, tag_match=tag_match, source_types=source_types,
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
            q.source_types,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"联合检索失败：{e}")
    return FederatedSearchResponse(
        query=q.query, results=external, local_results=local_results,
        errors=errors,
    )


@router.get("/connectors")
async def list_connectors():
    """列出已注册/启用的数据源（含出站代理配置与来源 origin，供风险提示）。"""
    manifests = connector_registry.list_manifests()
    return [
        {
            "name": m.name,
            "display_name": m.display_name,
            "version": m.version,
            "capabilities": m.capabilities,
            "enabled": connector_registry.is_enabled(m.name),
            "proxy_url": connector_registry.get_proxy(m.name),
            # "builtin" | "declarative" | "plugin"（ADR 0027 前端风险标识用）
            "origin": connector_registry.get_origin(m.name) or "builtin",
        }
        for m in manifests
    ]


@router.get("/plugins", response_model=PluginsResponse)
async def list_plugins():
    """插件管理面板数据（ADR 0027）：已加载插件 / 加载失败 / 一次性风险确认状态。"""
    from app import plugins as plugin_loader
    status = plugin_loader.get_plugin_status()
    return PluginsResponse(
        plugin_dir=status["plugin_dir"],
        plugins=status["plugins"],
        failures=status["failures"],
        notice_needed=plugin_loader.plugin_notice_needed(),
    )


@router.post("/plugins/acknowledge")
async def acknowledge_plugins_risk():
    """用户确认"第三方插件风险提示"（一次性，之后不再弹）。"""
    from app import plugins as plugin_loader
    plugin_loader.acknowledge_plugins()
    return {"ok": True}


@router.post("/connectors/{name}/proxy")
async def save_connector_proxy(name: str, body: ConnectorProxyRequest):
    """设置某数据源的出站代理（HTTP/HTTPS）。空串=清除（直连）。

    代理地址同样过 SSRF 校验（代理目标不能指向内网/回环/云元数据，
    代理场景不放行回环，见 ADR 0015）。
    """
    if connector_registry.get_connector(name) is None:
        raise HTTPException(status_code=404, detail=f"数据源 {name} 未注册")
    proxy_url = (body.proxy_url or "").strip()
    try:
        if proxy_url:
            validate_proxy_url(proxy_url)
    except ConnectorError as e:
        raise HTTPException(status_code=400, detail=str(e))
    connector_registry.set_proxy(name, proxy_url)
    connector_persistence.save_connector_proxy(name, proxy_url)
    return {
        "name": name,
        "proxy_url": connector_registry.get_proxy(name),
        "message": "代理已设置" if proxy_url else "已清除代理（直连）",
    }


@router.post("/connectors/{name}/test-proxy")
async def test_connector_proxy(name: str, body: ConnectorProxyRequest):
    """验证某数据源能否通过指定代理访问其 base_url。

    只校验代理地址的 SSRF + TCP 连通性（任何 HTTP 响应都算连通，
    连接失败/超时才算不可用），不触发真实业务请求。
    """
    conn = connector_registry.get_connector(name)
    if conn is None:
        raise HTTPException(status_code=404, detail=f"数据源 {name} 未注册")
    proxy_url = (body.proxy_url or "").strip()
    try:
        if proxy_url:
            validate_proxy_url(proxy_url)
    except ConnectorError as e:
        raise HTTPException(status_code=400, detail=str(e))

    base_url = getattr(conn, "manifest", None).base_url if getattr(conn, "manifest", None) else None
    if not base_url:
        raise HTTPException(status_code=400, detail=f"数据源 {name} 没有 base_url 可测试")
    import httpx
    try:
        resp = httpx.get(base_url, timeout=8.0, proxy=proxy_url or None,
                         follow_redirects=True)
        if proxy_url:
            return {"ok": True, "message": f"通过代理连接成功（{base_url} → HTTP {resp.status_code}）"}
        return {"ok": True, "message": f"直连成功（{base_url} → HTTP {resp.status_code}）"}
    except httpx.HTTPError as e:
        mode = "代理" if proxy_url else "直连"
        return {"ok": False, "message": f"{mode}连接失败（{base_url}）：{e}"}


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
    """在子线程中执行收藏入库。外部封面图缓存到本地（失败不阻塞）。

    Connector 支持 get_detail 时，**顺带下载完整资料**（简介+角色小传）：
    - 文本写入 external_reference chunk（参与 RAG 检索，加权更低，见 ADR 0025）；
    - 详情存 raw_metadata（ADR 0016 结构，含 reference_text，供角色墙聚合与
      后续重下判重）；
    详情失败则降级为搜索级信息（只存简介摘要）。
    """
    from app.database import SessionLocal
    from app.external_refs import (
        ensure_external_reference_chunks,
        get_stored_reference,
        with_reference_text,
    )
    from app.images import cache_external_image
    from app.connectors.base import ConnectorError

    # 1) 尝试拉详情（角色/标签/简介/封面），失败不阻塞入库
    detail = None
    conn = connector_registry.get_connector(req.source)
    if conn is not None and "get_detail" in (conn.manifest.capabilities or []):
        try:
            detail = conn.get_detail(req.external_id)
        except ConnectorError:
            detail = None

    title = detail.title if detail and detail.title else req.title
    description = detail.description if detail and detail.description else req.description or ""
    image_url = detail.image_url if detail and detail.image_url else req.image_url
    tags = (detail.metadata.get("tags") or req.tags) if detail else req.tags
    raw_metadata = None
    reference_text = ""
    if detail is not None:
        # 统一 raw_metadata 结构（见 ADR 0016）：detail 内含完整资料 reference_text
        raw_metadata = {"source": req.source, "detail": with_reference_text(detail)}
        reference_text = raw_metadata["detail"]["metadata"].get("reference_text") or ""

    local_thumb = cache_external_image(image_url)
    db = SessionLocal()
    try:
        obj = ingest.ingest_external(
            source=req.source,
            external_id=req.external_id,
            title=title,
            content=description,
            image_url=image_url,
            tags=tags,
            raw_metadata=raw_metadata,
            reference_text=reference_text,
            db=db,
        )
        # 幂等命中/旧条目：完整资料与已存不一致时重建 external_reference chunk
        if detail is not None and get_stored_reference(obj) != reference_text:
            ensure_external_reference_chunks(obj, reference_text, db=db)
        # 详情回填：raw_metadata 有内容则覆盖（保证角色墙数据落库）
        if raw_metadata is not None:
            obj.raw_metadata = raw_metadata
            # P1 世界轴列：入库时即提炼（只填 NULL，不覆盖用户已填）
            work_model.apply_work_columns(obj, raw_metadata)
            db.commit()
            db.refresh(obj)
            # P4（ADR 0048）：重建该作品的角色索引（从 raw_metadata 提炼）
            characters.sync_characters(obj, db)
            db.commit()
            db.refresh(obj)
        # 本地缩略图路径存到 file_path（与 image_url 区分：本地 vs 外部）
        if local_thumb and not obj.file_path:
            obj.file_path = local_thumb
            db.commit()
            db.refresh(obj)
        # P2（ADR 0046）：收藏关系维护 + 首次收藏生成"收藏时刻"最轻 Memory
        collections.on_collect(obj, db)
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


def _detail_to_out(detail) -> ExternalDetailOut:
    meta = detail.metadata or {}
    return ExternalDetailOut(
        source=detail.source,
        title=detail.title,
        external_id=detail.external_id,
        description=detail.description or "",
        image_url=detail.image_url,
        rating=meta.get("rating"),
        tags=meta.get("tags") or [],
        characters=meta.get("characters") or [],
        metadata=meta,
    )


@router.get("/external/detail", response_model=ExternalDetailOut)
async def external_detail(source: str, external_id: str):
    """live 拉取某数据源 get_detail（联合搜索结果点开详情用，不落库）。"""
    conn = connector_registry.get_connector(source)
    if conn is None or "get_detail" not in (conn.manifest.capabilities or []):
        raise HTTPException(status_code=404, detail=f"数据源 {source} 不支持详情")
    from app.connectors.base import ConnectorError
    try:
        detail = await run_in_threadpool(conn.get_detail, external_id)
    except ConnectorError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return _detail_to_out(detail)


@router.get("/items/{item_id}/detail", response_model=ItemDetailOut)
async def item_detail(item_id: int, db: Session = Depends(get_db)):
    """已收藏条目详情：从 raw_metadata 提炼 detail（含角色），供详情弹层与
    Review Studio Overview（ADR 0026：含完整简介、reference_text、热度替代数据）。"""
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="条目不存在")
    raw = item.raw_metadata if isinstance(item.raw_metadata, dict) else None
    detail = (raw or {}).get("detail")
    if not isinstance(detail, dict):
        detail = None
    meta = detail.get("metadata") if isinstance(detail, dict) else {}
    if not isinstance(meta, dict):
        meta = {}
    from app.external_refs import extract_social_meta
    return ItemDetailOut(
        id=item.id,
        title=item.title,
        source=item.source,
        external_id=item.external_id,
        image_url=item.image_url or (detail or {}).get("image_url"),
        file_path=item.file_path,
        description=(detail or {}).get("description") or item.content,
        rating=meta.get("rating"),
        my_rating=reviews.get_my_rating(item_id, db=db),
        tags=[t.name for t in item.tags] or meta.get("tags") or [],
        characters=meta.get("characters") or [],
        reference_text=meta.get("reference_text"),
        social=extract_social_meta(meta),
        raw_metadata=raw,
        created_at=item.created_at,
        work_type=item.work_type,
        alternative_title=item.alternative_title,
        release_date=item.release_date,
        collection_status=item.collection.status if item.collection else None,
        collected_at=item.collection.added_at if item.collection else None,
        favorite=bool(item.collection.favorite) if item.collection else False,
    )


def _title_key(title: Optional[str]) -> str:
    """跨来源标题近似匹配键（ADR 0026 多来源切换）：小写 + 去除空格/全角标点/括号。

    用于"同一作品从不同来源各自收藏一份"的场景（Bangumi 中文名 ↔ 萌娘百科同名
    页面等），不做完整合并去重，只做切换查看。
    """
    if not title:
        return ""
    s = str(title).lower().strip()
    s = re.sub(r"[：:（）()\[\]【】「」『』《》\-—_·、，。.,\s]", "", s)
    return s


@router.get("/items/{item_id}/related", response_model=List[RelatedSourceOut])
async def related_external_items(item_id: int, db: Session = Depends(get_db)):
    """同一作品跨来源的兄弟条目（Review Studio Overview 多来源切换用）。

    按规范化标题匹配其它非本地来源的已收藏条目；匹配不到返回空列表
    （如 VNDB 英文名 vs Bangumi 中文名通常不匹配，属预期）。
    """
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="条目不存在")
    if item.source == "local":
        return []
    key = _title_key(item.title)
    if not key:
        return []
    others = db.query(Item).filter(
        Item.source != "local", Item.source != item.source
    ).all()
    siblings = []
    for it in others:
        if it.id == item.id or _title_key(it.title) != key:
            continue
        raw = it.raw_metadata if isinstance(it.raw_metadata, dict) else None
        detail = raw.get("detail") if isinstance(raw, dict) else None
        meta = detail.get("metadata") if isinstance(detail, dict) else {}
        if not isinstance(meta, dict):
            meta = {}
        siblings.append(RelatedSourceOut(
            id=it.id,
            title=it.title,
            source=it.source,
            external_id=it.external_id,
            image_url=it.image_url or (detail or {}).get("image_url"),
            rating=meta.get("rating"),
        ))
    return siblings


@router.post("/items/{item_id}/refresh-external", response_model=ItemDetailOut)
async def refresh_external_item(item_id: int, db: Session = Depends(get_db)):
    """手动刷新某外部条目的完整资料（重新拉取最新版本，不锁死为一次性快照）。

    - 走 Connector 令牌桶限流（get_detail 内部 acquire），不会不受控打 API；
    - 重建 raw_metadata 与 external_reference chunk（简介+角色小传参与 RAG）；
    - 数据源不支持 get_detail / 拉取失败时返回 502，本地数据保持不变。
    """
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="条目不存在")
    if item.source == "local" or not item.external_id:
        raise HTTPException(status_code=400, detail="仅外部收藏条目支持刷新")

    conn = connector_registry.get_connector(item.source)
    if conn is None or "get_detail" not in (conn.manifest.capabilities or []):
        raise HTTPException(status_code=400, detail=f"数据源 {item.source} 不支持详情刷新")

    from app.external_refs import with_reference_text, replace_external_reference_chunks

    def _sync():
        from app.database import SessionLocal
        db2 = SessionLocal()
        try:
            fresh = db2.get(Item, item_id)
            if fresh is None:
                raise HTTPException(status_code=404, detail="条目不存在")
            detail = conn.get_detail(fresh.external_id)
            text = with_reference_text(detail)
            reference = (text.get("metadata") or {}).get("reference_text") or ""
            fresh.raw_metadata = {"source": fresh.source, "detail": text}
            if detail.image_url and not fresh.file_path:
                fresh.image_url = detail.image_url
            replace_external_reference_chunks(fresh, reference, db=db2)
            db2.commit()
            db2.refresh(fresh)
            return fresh
        finally:
            db2.close()

    from app.connectors.base import ConnectorError
    try:
        refreshed = await run_in_threadpool(_sync)
    except ConnectorError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"刷新失败：{e}")

    db.expire_all()  # 丢弃请求会话内的旧缓存，让 item_detail 读到线程会话的写入
    return await item_detail(refreshed.id, db=db)


@router.post("/external/backfill-reference")
async def backfill_external_reference_route(
    limit: int = Query(5, ge=1, le=50),
    source: Optional[str] = Query(None),
):
    """批量补齐历史收藏的完整外部资料（非阻塞后台单飞，复用令牌桶限流）。

    与角色墙懒加载补详情同模式：每次最多补 limit 条，可多次调用推进；
    已补齐条目自动跳过。返回是否本次实际启动了后台任务。
    """
    from app import external_refs
    started = external_refs.backfill_async(limit=limit, source=source)
    return {
        "started": started,
        "message": "已启动补齐任务" if started else "已有补齐任务在运行，请稍后再试",
        "limit": limit,
    }


def bangumi_import_backfill(limit: int = 10) -> bool:
    """角色墙懒加载补详情（非阻塞后台单飞；单次最多补 limit 条）。"""
    from app import bangumi_import
    try:
        return bangumi_import.backfill_async(limit=limit)
    except Exception:
        return False


@router.get("/characters", response_model=CharactersResponse)
async def list_characters(db: Session = Depends(get_db)):
    """角色墙（P4 / ADR 0048）：从 characters 实体表跨作品聚合（不再实时扫描 raw_metadata）。

    批量导入的 bangumi 条目没有角色详情，这里做**懒加载补详情**（后台非阻塞
    单飞，受令牌桶限流约束分批推进），补详情后角色索引由同步逻辑重建。
    """
    bangumi_import_backfill()  # 非阻塞触发补详情
    rows = db.query(Character).options(selectinload(Character.works)) \
        .order_by(Character.name).all()
    chars = []
    for ch in rows:
        chars.append({
            "id": ch.id,
            "name": ch.name,
            "image_url": ch.image_url,
            "relation": ch.relation,
            "summary": ch.summary or "",
            "actors": json.loads(ch.actors) if ch.actors else [],
            "source": ch.source,
            "works": [
                {"item_id": w.id, "title": w.title, "image_url": w.image_url, "source": w.source}
                for w in ch.works
            ],
        })
    return {"characters": chars}


@router.get("/voice-relations")
async def voice_relations(db: Session = Depends(get_db)):
    """声优关系聚合（ADR 0032 / P4）：声优 → 配过的角色 → 所属作品 三层关系。

    从 characters 实体表读取（actors 为 JSON 数组，作品经 character_works 关联）。
    返回：works（作品）/ actors（含各自 works→roles）/ stats（含缺失声优的角色数）。
    """
    rows = db.query(Character).options(selectinload(Character.works)).all()
    works: dict = {}
    actor_map: dict = {}
    missing_actor_chars = 0
    for ch in rows:
        if not ch.works:
            continue
        actors = json.loads(ch.actors) if ch.actors else []
        if not actors:
            missing_actor_chars += 1
        for w in ch.works:
            works[w.id] = {"item_id": w.id, "title": w.title,
                           "image_url": w.image_url, "source": w.source}
        for a in actors:
            a_name = str(a).strip()
            if not a_name:
                continue
            entry = actor_map.setdefault(a_name, {"name": a_name, "works": {}})
            for w in ch.works:
                ww = entry["works"].setdefault(w.id, {"item_id": w.id, "title": w.title, "roles": []})
                if ch.name not in ww["roles"]:
                    ww["roles"].append(ch.name)

    actors = [
        {
            "name": a["name"],
            "work_count": len(a["works"]),
            "role_count": sum(len(x["roles"]) for x in a["works"].values()),
            "works": [
                {"item_id": wid, "title": w["title"], "roles": w["roles"]}
                for wid, w in a["works"].items()
            ],
        }
        for a in actor_map.values()
    ]
    return {
        "works": list(works.values()),
        "actors": actors,
        "stats": {
            "actor_count": len(actors),
            "work_count": len(works),
            "missing_actor_chars": missing_actor_chars,
        },
    }


# ========== RAG 问答 ==========

@router.post("/rag/query", response_model=RAGResponse)
async def rag_query(q: QueryRequest):
    try:
        chunks = await run_in_threadpool(
            retrieval.retrieve_chunks,
            query=q.query, top_k=q.top_k or settings.top_k, tags=q.tag_filter,
            tag_match=q.tag_match, source_types=q.source_types,
        )
        if not chunks:
            return RAGResponse(
                answer="知识库中没有检索到与问题相关的资料。",
                retrieved_chunks=[],
            )
        answer = await rag.generate_answer_non_stream(q.query, chunks)
    except EmbeddingError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except rag.AIAnswerDisabled as e:
        # AI 问答未启用：返回明确的引导提示（非故障）
        return RAGResponse(
            answer=f"⚠️ {e}",
            retrieved_chunks=[],
        )
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
            tag_match=q.tag_match, source_types=q.source_types,
        )
    except EmbeddingError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检索失败：{e}")

    sources = list(chunks)

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
