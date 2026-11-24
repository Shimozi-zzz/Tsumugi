from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.database import get_db
from backend.db.models import Collection, CollectionItem, Game
from backend.schemas import (
    CollectionCreate,
    CollectionGamesUpdate,
    CollectionItemInput,
    CollectionItemsUpdate,
    CollectionOut,
    CollectionUpdate,
)
from backend.services.thumbnail_service import build_thumb_api_url

router = APIRouter(prefix="/api/collections", tags=["Collections"])


def _is_completed_status(status: str | None) -> bool:
    return (status or "").strip().lower() in ("done", "completed")


def _is_playing_status(status: str | None) -> bool:
    return (status or "").strip().lower() == "playing"


def _build_item_summary(item: CollectionItem, game: Game) -> dict[str, Any]:
    cover_src = ""
    if game.media:
        cover_src = (game.media.cover_path or game.media.cover_thumb_path or "").strip()
    return {
        "game_id": game.id,
        "title": game.title,
        "sub_title": game.sub_title or "",
        "cover_thumb_url": build_thumb_api_url(cover_src, "sm") if cover_src else "",
        "cover_path": cover_src,
        "play_status": (game.status or "todo").strip().lower(),
        "is_nsfw": bool(game.is_nsfw),
        "rating_overall": game.rating_overall,
        "relation_label": (item.relation_label or "").strip(),
        "position": int(item.position or 0),
        "added_at": item.added_at,
    }


def _compute_completion_stats(items: list[dict[str, Any]]) -> dict[str, int]:
    total = len(items)
    completed = sum(1 for it in items if _is_completed_status(it.get("play_status")))
    playing = sum(1 for it in items if _is_playing_status(it.get("play_status")))
    unplayed = max(0, total - completed - playing)
    return {
        "total_count": total,
        "completed_count": completed,
        "playing_count": playing,
        "unplayed_count": unplayed,
    }


async def _serialize_collections_batch(
    db: AsyncSession,
    cols: list[Collection],
) -> list[dict[str, Any]]:
    if not cols:
        return []

    col_ids = [c.id for c in cols]
    rows = (
        await db.execute(
            select(CollectionItem, Game)
            .join(Game, Game.id == CollectionItem.game_id)
            .where(CollectionItem.collection_id.in_(col_ids))
            .options(selectinload(Game.media))
            .order_by(
                CollectionItem.collection_id.asc(),
                CollectionItem.position.asc(),
                CollectionItem.id.asc(),
            )
        )
    ).all()

    grouped_items: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item, game in rows:
        grouped_items[item.collection_id].append(_build_item_summary(item, game))

    serialized: list[dict[str, Any]] = []
    for col in cols:
        item_list = grouped_items.get(col.id, [])
        stats = _compute_completion_stats(item_list)
        serialized.append(
            {
                "id": col.id,
                "name": col.name,
                "description": col.description or "",
                "collection_type": col.collection_type or "series",
                "sort_order": col.sort_order,
                "created_at": col.created_at,
                "updated_at": col.updated_at or col.created_at,
                "game_ids": [it["game_id"] for it in item_list],
                "items": item_list,
                **stats,
            }
        )
    return serialized


async def _serialize_collection(db: AsyncSession, col: Collection) -> dict[str, Any]:
    return (await _serialize_collections_batch(db, [col]))[0]


async def serialize_game_collections(
    db: AsyncSession,
    game_id: int,
) -> list[dict[str, Any]]:
    """查询指定游戏所属的全部合集，附带各合集按 position 排好序的成员摘要"""
    col_ids = list(
        (
            await db.execute(
                select(Collection.id)
                .join(CollectionItem, CollectionItem.collection_id == Collection.id)
                .where(CollectionItem.game_id == game_id)
                .order_by(Collection.sort_order.asc(), Collection.id.asc())
            )
        )
        .scalars()
        .all()
    )
    if not col_ids:
        return []

    cols = list(
        (
            await db.execute(
                select(Collection)
                .where(Collection.id.in_(col_ids))
                .order_by(Collection.sort_order.asc(), Collection.id.asc())
            )
        )
        .scalars()
        .all()
    )
    batch = await _serialize_collections_batch(db, cols)
    memberships: list[dict[str, Any]] = []
    for col_data in batch:
        current_entry = next(
            (it for it in col_data["items"] if it["game_id"] == game_id),
            None,
        )
        memberships.append(
            {
                "id": col_data["id"],
                "name": col_data["name"],
                "description": col_data["description"],
                "collection_type": col_data["collection_type"],
                "relation_label": current_entry["relation_label"] if current_entry else "",
                "position": current_entry["position"] if current_entry else 0,
                "total_count": col_data["total_count"],
                "completed_count": col_data["completed_count"],
                "items": col_data["items"],
            }
        )
    return memberships


async def _replace_items_atomic(
    db: AsyncSession,
    col: Collection,
    entries: list[CollectionItemInput],
) -> None:
    """原子化重写合集内有序成员与关系标签，保留既有条目的 added_at 时间戳"""
    existing_rows = list(
        (
            await db.execute(
                select(CollectionItem).where(CollectionItem.collection_id == col.id)
            )
        )
        .scalars()
        .all()
    )
    added_at_by_gid = {row.game_id: row.added_at for row in existing_rows}

    deduped: list[tuple[int, str]] = []
    seen_gids: set[int] = set()
    for entry in entries:
        gid = int(entry.game_id)
        if gid in seen_gids:
            continue
        seen_gids.add(gid)
        label = (entry.relation_label or "").strip()[:32]
        deduped.append((gid, label))

    valid_ids: set[int] = set()
    if deduped:
        valid_ids = set(
            (
                await db.execute(
                    select(Game.id).where(Game.id.in_([gid for gid, _ in deduped]))
                )
            )
            .scalars()
            .all()
        )

    await db.execute(delete(CollectionItem).where(CollectionItem.collection_id == col.id))
    await db.flush()

    pos = 0
    for gid, label in deduped:
        if gid not in valid_ids:
            continue
        db.add(
            CollectionItem(
                collection_id=col.id,
                game_id=gid,
                position=pos,
                relation_label=label,
                added_at=added_at_by_gid.get(gid) or datetime.now(),
            )
        )
        pos += 1

    col.updated_at = datetime.now()


async def _compact_positions(db: AsyncSession, collection_id: int) -> None:
    rows = list(
        (
            await db.execute(
                select(CollectionItem)
                .where(CollectionItem.collection_id == collection_id)
                .order_by(CollectionItem.position.asc(), CollectionItem.id.asc())
            )
        )
        .scalars()
        .all()
    )
    for idx, row in enumerate(rows):
        row.position = idx


@router.get("", response_model=list[CollectionOut])
async def list_collections(db: AsyncSession = Depends(get_db)):
    """返回全部系列合集/分组，附带按 position 排好序的作品轻量摘要与完成进度统计"""
    cols = list(
        (
            await db.execute(
                select(Collection).order_by(Collection.sort_order.asc(), Collection.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return await _serialize_collections_batch(db, cols)


@router.post("", response_model=CollectionOut)
async def create_collection(
    payload: CollectionCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建新系列合集/分组，可选同时指定有序作品列表与关系标签"""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="合集名称不能为空")

    max_order = (await db.execute(select(func.max(Collection.sort_order)))).scalar()
    next_order = (max_order + 1) if max_order is not None else 0
    now = datetime.now()

    col = Collection(
        name=name,
        description=(payload.description or "").strip(),
        collection_type=payload.collection_type or "series",
        sort_order=next_order,
        updated_at=now,
    )
    db.add(col)
    await db.flush()

    initial_entries: list[CollectionItemInput] = []
    if payload.items is not None:
        initial_entries = list(payload.items)
    elif payload.game_ids:
        initial_entries = [CollectionItemInput(game_id=gid) for gid in payload.game_ids]

    if initial_entries:
        await _replace_items_atomic(db, col, initial_entries)

    await db.commit()
    await db.refresh(col)
    return await _serialize_collection(db, col)


@router.patch("/{collection_id}", response_model=CollectionOut)
async def update_collection(
    collection_id: int,
    payload: CollectionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新合集名称、说明、类型或展示排序"""
    col = await db.get(Collection, collection_id)
    if not col:
        raise HTTPException(status_code=404, detail="未找到指定合集")

    if payload.name is not None:
        cleaned = payload.name.strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="合集名称不能为空")
        col.name = cleaned
    if payload.description is not None:
        col.description = payload.description.strip()
    if payload.collection_type is not None:
        col.collection_type = payload.collection_type
    if payload.sort_order is not None:
        col.sort_order = payload.sort_order
    col.updated_at = datetime.now()

    await db.commit()
    await db.refresh(col)
    return await _serialize_collection(db, col)


@router.delete("/{collection_id}")
async def delete_collection(
    collection_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除合集（仅解除关联关系，绝不删除游戏本体）"""
    col = await db.get(Collection, collection_id)
    if not col:
        raise HTTPException(status_code=404, detail="未找到指定合集")

    await db.execute(delete(CollectionItem).where(CollectionItem.collection_id == collection_id))
    await db.delete(col)
    await db.commit()
    return {"status": "deleted", "collection_id": collection_id}


@router.put("/{collection_id}/items", response_model=CollectionOut)
async def replace_collection_items(
    collection_id: int,
    payload: list[CollectionItemInput] | CollectionItemsUpdate,
    db: AsyncSession = Depends(get_db),
):
    """原子化保存合集内作品成员、顺序与关系标签（兼容直接传数组或 {items: [...]}）"""
    col = await db.get(Collection, collection_id)
    if not col:
        raise HTTPException(status_code=404, detail="未找到指定合集")

    entries = payload if isinstance(payload, list) else payload.items
    await _replace_items_atomic(db, col, entries)
    await db.commit()
    await db.refresh(col)
    return await _serialize_collection(db, col)


@router.post("/{collection_id}/items", response_model=CollectionOut)
async def add_item_to_collection(
    collection_id: int,
    payload: CollectionItemInput,
    db: AsyncSession = Depends(get_db),
):
    """快捷将单部作品加入合集（若已存在则更新其关系标签）"""
    col = await db.get(Collection, collection_id)
    if not col:
        raise HTTPException(status_code=404, detail="未找到指定合集")
    game = await db.get(Game, payload.game_id)
    if not game:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    existing = (
        await db.execute(
            select(CollectionItem).where(
                CollectionItem.collection_id == collection_id,
                CollectionItem.game_id == payload.game_id,
            )
        )
    ).scalar_one_or_none()
    label = (payload.relation_label or "").strip()[:32]

    if existing:
        if payload.relation_label is not None:
            existing.relation_label = label
    else:
        max_pos = (
            await db.execute(
                select(func.max(CollectionItem.position)).where(
                    CollectionItem.collection_id == collection_id
                )
            )
        ).scalar()
        next_pos = (int(max_pos) + 1) if max_pos is not None else 0
        db.add(
            CollectionItem(
                collection_id=collection_id,
                game_id=payload.game_id,
                position=next_pos,
                relation_label=label,
            )
        )
    col.updated_at = datetime.now()
    await db.commit()
    await db.refresh(col)
    return await _serialize_collection(db, col)


@router.delete("/{collection_id}/items/{game_id}", response_model=CollectionOut)
async def remove_item_from_collection(
    collection_id: int,
    game_id: int,
    db: AsyncSession = Depends(get_db),
):
    """快捷将单部作品移出合集（不删除游戏本体，并自动重排剩余 position）"""
    col = await db.get(Collection, collection_id)
    if not col:
        raise HTTPException(status_code=404, detail="未找到指定合集")

    await db.execute(
        delete(CollectionItem).where(
            CollectionItem.collection_id == collection_id,
            CollectionItem.game_id == game_id,
        )
    )
    await _compact_positions(db, collection_id)
    col.updated_at = datetime.now()
    await db.commit()
    await db.refresh(col)
    return await _serialize_collection(db, col)


# ──────────────────── 向后兼容旧版 /games 路由别名 ────────────────────


@router.put("/{collection_id}/games", response_model=CollectionOut)
async def replace_collection_games(
    collection_id: int,
    payload: CollectionGamesUpdate,
    db: AsyncSession = Depends(get_db),
):
    """向后兼容：按 game_ids 覆盖合集内作品成员（自动保留既有成员的关系标签）"""
    col = await db.get(Collection, collection_id)
    if not col:
        raise HTTPException(status_code=404, detail="未找到指定合集")

    existing_rows = list(
        (
            await db.execute(
                select(CollectionItem).where(CollectionItem.collection_id == collection_id)
            )
        )
        .scalars()
        .all()
    )
    existing_labels = {row.game_id: row.relation_label or "" for row in existing_rows}
    entries = [
        CollectionItemInput(game_id=gid, relation_label=existing_labels.get(gid, ""))
        for gid in payload.game_ids
    ]
    await _replace_items_atomic(db, col, entries)
    await db.commit()
    await db.refresh(col)
    return await _serialize_collection(db, col)


@router.post("/{collection_id}/games/{game_id}", response_model=CollectionOut)
async def add_game_to_collection(
    collection_id: int,
    game_id: int,
    db: AsyncSession = Depends(get_db),
):
    """向后兼容：将单款游戏快捷加入合集"""
    return await add_item_to_collection(
        collection_id,
        CollectionItemInput(game_id=game_id),
        db,
    )


@router.delete("/{collection_id}/games/{game_id}", response_model=CollectionOut)
async def remove_game_from_collection(
    collection_id: int,
    game_id: int,
    db: AsyncSession = Depends(get_db),
):
    """向后兼容：将单款游戏从合集中移出（不删除游戏本体）"""
    return await remove_item_from_collection(collection_id, game_id, db)
