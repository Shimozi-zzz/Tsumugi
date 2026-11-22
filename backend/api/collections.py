from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import Collection, CollectionGame, Game
from backend.schemas import (
    CollectionCreate,
    CollectionGamesUpdate,
    CollectionOut,
    CollectionUpdate,
)

router = APIRouter(prefix="/api/collections", tags=["Collections"])


async def _serialize_collection(db: AsyncSession, col: Collection) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(CollectionGame.game_id)
            .where(CollectionGame.collection_id == col.id)
            .order_by(CollectionGame.game_id.asc())
        )
    ).scalars().all()
    return {
        "id": col.id,
        "name": col.name,
        "sort_order": col.sort_order,
        "created_at": col.created_at,
        "game_ids": list(rows),
    }


@router.get("", response_model=list[CollectionOut])
async def list_collections(db: AsyncSession = Depends(get_db)):
    """返回全部自定义分组及每个分组包含的游戏 ID 列表"""
    cols = list(
        (
            await db.execute(
                select(Collection).order_by(Collection.sort_order.asc(), Collection.id.asc())
            )
        )
        .scalars()
        .all()
    )
    if not cols:
        return []

    links = (
        await db.execute(
            select(CollectionGame.collection_id, CollectionGame.game_id).order_by(
                CollectionGame.game_id.asc()
            )
        )
    ).all()
    grouped: dict[int, list[int]] = defaultdict(list)
    for col_id, game_id in links:
        grouped[col_id].append(game_id)

    return [
        {
            "id": col.id,
            "name": col.name,
            "sort_order": col.sort_order,
            "created_at": col.created_at,
            "game_ids": grouped.get(col.id, []),
        }
        for col in cols
    ]


@router.post("", response_model=CollectionOut)
async def create_collection(
    payload: CollectionCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建新分组，可选同时指定初始包含的游戏 ID 列表"""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="分组名称不能为空")

    max_order = (await db.execute(select(func.max(Collection.sort_order)))).scalar()
    next_order = (max_order + 1) if max_order is not None else 0

    col = Collection(name=name, sort_order=next_order)
    db.add(col)
    await db.flush()

    if payload.game_ids:
        unique_ids = list(dict.fromkeys(payload.game_ids))
        valid_ids = set(
            (await db.execute(select(Game.id).where(Game.id.in_(unique_ids)))).scalars().all()
        )
        for gid in unique_ids:
            if gid in valid_ids:
                db.add(CollectionGame(collection_id=col.id, game_id=gid))

    await db.commit()
    await db.refresh(col)
    return await _serialize_collection(db, col)


@router.patch("/{collection_id}", response_model=CollectionOut)
async def update_collection(
    collection_id: int,
    payload: CollectionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """重命名分组或更新排序"""
    col = await db.get(Collection, collection_id)
    if not col:
        raise HTTPException(status_code=404, detail="未找到指定分组")

    if payload.name is not None:
        cleaned = payload.name.strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="分组名称不能为空")
        col.name = cleaned
    if payload.sort_order is not None:
        col.sort_order = payload.sort_order

    await db.commit()
    await db.refresh(col)
    return await _serialize_collection(db, col)


@router.delete("/{collection_id}")
async def delete_collection(
    collection_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除分组（仅清理关联关系，绝不删除游戏本体）"""
    col = await db.get(Collection, collection_id)
    if not col:
        raise HTTPException(status_code=404, detail="未找到指定分组")

    await db.execute(delete(CollectionGame).where(CollectionGame.collection_id == collection_id))
    await db.delete(col)
    await db.commit()
    return {"status": "deleted", "collection_id": collection_id}


@router.put("/{collection_id}/games", response_model=CollectionOut)
async def replace_collection_games(
    collection_id: int,
    payload: CollectionGamesUpdate,
    db: AsyncSession = Depends(get_db),
):
    """批量覆盖分组内的游戏成员列表"""
    col = await db.get(Collection, collection_id)
    if not col:
        raise HTTPException(status_code=404, detail="未找到指定分组")

    await db.execute(delete(CollectionGame).where(CollectionGame.collection_id == collection_id))

    if payload.game_ids:
        unique_ids = list(dict.fromkeys(payload.game_ids))
        valid_ids = set(
            (await db.execute(select(Game.id).where(Game.id.in_(unique_ids)))).scalars().all()
        )
        for gid in unique_ids:
            if gid in valid_ids:
                db.add(CollectionGame(collection_id=collection_id, game_id=gid))

    await db.commit()
    return await _serialize_collection(db, col)


@router.post("/{collection_id}/games/{game_id}", response_model=CollectionOut)
async def add_game_to_collection(
    collection_id: int,
    game_id: int,
    db: AsyncSession = Depends(get_db),
):
    """将单款游戏快捷加入分组"""
    col = await db.get(Collection, collection_id)
    if not col:
        raise HTTPException(status_code=404, detail="未找到指定分组")
    game = await db.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    existing = await db.get(CollectionGame, (collection_id, game_id))
    if not existing:
        db.add(CollectionGame(collection_id=collection_id, game_id=game_id))
        await db.commit()

    return await _serialize_collection(db, col)


@router.delete("/{collection_id}/games/{game_id}", response_model=CollectionOut)
async def remove_game_from_collection(
    collection_id: int,
    game_id: int,
    db: AsyncSession = Depends(get_db),
):
    """将单款游戏从分组中移出（不删除游戏本体）"""
    col = await db.get(Collection, collection_id)
    if not col:
        raise HTTPException(status_code=404, detail="未找到指定分组")

    await db.execute(
        delete(CollectionGame).where(
            CollectionGame.collection_id == collection_id,
            CollectionGame.game_id == game_id,
        )
    )
    await db.commit()
    return await _serialize_collection(db, col)
