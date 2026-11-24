import shutil
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.api.settings import DEFAULT_SETTINGS, resolve_bangumi_token
from backend.core.config import ASSETS_DIR
from backend.core.os_adapter import os_adapter
from backend.db.database import get_db
from backend.db.models import AppStateSetting, CollectionGame, Game, GameMediaPath, PlayRecord, PlaySession
from backend.schemas import BangumiSyncRequest, GameCreate, GameOut, GameUpdate, PlaySessionOut
from backend.scrapers.bangumi import BANGUMI_USER_AGENT, BGM_BASE_URL
from backend.services.media_service import generate_pinyin_initials
from backend.services.process_tracker import process_tracker
from backend.services.thumbnail_service import (
    invalidate_thumbnails_for_game,
    invalidate_thumbnails_for_path,
)

router = APIRouter(prefix="/api/games", tags=["games"])

STATUS_QUERY_EQUIVALENTS: dict[str, tuple[str, ...]] = {
    "unplayed": ("unplayed", "todo"),
    "todo": ("todo", "unplayed"),
    "playing": ("playing",),
    "completed": ("completed", "done"),
    "done": ("done", "completed"),
}

BANGUMI_COLLECTION_TYPE_MAP: dict[str, tuple[int, str]] = {
    "unplayed": (1, "想玩"),
    "todo": (1, "想玩"),
    "playing": (3, "在玩"),
    "completed": (2, "玩过"),
    "done": (2, "玩过"),
}


async def _set_last_active_game(db: AsyncSession, game_id: int) -> None:
    """实时更新断点记忆，记录最后查看或启动的游戏"""
    setting = await db.get(AppStateSetting, "last_active_game_id")
    if setting:
        setting.value = game_id
    else:
        db.add(AppStateSetting(key="last_active_game_id", value=game_id))


async def _load_game_full(db: AsyncSession, game_id: int) -> Game | None:
    stmt = (
        select(Game)
        .where(Game.id == game_id)
        .options(selectinload(Game.media), selectinload(Game.play_record))
    )
    return (await db.execute(stmt)).scalar_one_or_none()


@router.get("", response_model=list[GameOut])
async def list_games(
    status: str | None = Query(
        None, description="按状态筛选: unplayed / todo / playing / completed / done"
    ),
    collection_id: int | None = Query(None, description="按回廊分组 ID 筛选"),
    tag: str | None = Query(None, description="按标签筛选"),
    q: str | None = Query(None, description="按标题、原名、开发者、发行商、拼音首字母模糊搜索"),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Game)
        .options(selectinload(Game.media), selectinload(Game.play_record))
        .order_by(Game.id.asc())
    )
    if collection_id is not None:
        stmt = stmt.join(CollectionGame, CollectionGame.game_id == Game.id).where(
            CollectionGame.collection_id == collection_id
        )

    if status and status != "all":
        norm_st = status.strip().lower()
        matched_statuses = STATUS_QUERY_EQUIVALENTS.get(norm_st)
        if matched_statuses:
            stmt = stmt.where(Game.status.in_(matched_statuses))
        else:
            stmt = stmt.where(Game.status == status)

    if q and q.strip():
        pattern = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                Game.title.ilike(pattern),
                Game.sub_title.ilike(pattern),
                Game.developer.ilike(pattern),
                Game.publisher.ilike(pattern),
                Game.pinyin_initials.ilike(pattern),
            )
        )

    result = await db.execute(stmt)
    games = list(result.scalars().all())

    if tag and tag.strip():
        target_tag = tag.strip()
        games = [g for g in games if target_tag in (g.tags or [])]

    return games


@router.post("", response_model=GameOut)
async def create_game(payload: GameCreate, db: AsyncSession = Depends(get_db)):
    resolved_bgm_id = (
        payload.bangumi_id.strip()
        or str((payload.external_ids or {}).get("bgm") or (payload.external_ids or {}).get("bangumi") or "").strip()
    )
    game = Game(
        title=payload.title,
        sub_title=payload.sub_title,
        pinyin_initials=generate_pinyin_initials(payload.title),
        developer=payload.developer,
        publisher=payload.publisher,
        release_date=payload.release_date,
        synopsis=payload.synopsis,
        tags=payload.tags,
        status=payload.status,
        edition=payload.edition,
        is_nsfw=payload.is_nsfw,
        source_platform=payload.source_platform,
        bangumi_id=resolved_bgm_id,
        series=payload.series.strip(),
        external_ids=payload.external_ids,
        locked_fields=payload.locked_fields,
    )
    media_data = payload.media.model_dump() if payload.media else {}
    game.media = GameMediaPath(**media_data)
    game.play_record = PlayRecord(total_seconds=0)

    db.add(game)
    await db.flush()
    await _set_last_active_game(db, game.id)
    await db.commit()

    created = await _load_game_full(db, game.id)
    assert created is not None
    return created


@router.get("/{game_id}", response_model=GameOut)
async def get_game(
    game_id: int,
    record_active: bool = True,
    db: AsyncSession = Depends(get_db),
):
    game = await _load_game_full(db, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    if record_active:
        await _set_last_active_game(db, game.id)
        await db.commit()
    return game


@router.patch("/{game_id}", response_model=GameOut)
async def update_game(
    game_id: int, payload: GameUpdate, db: AsyncSession = Depends(get_db)
):
    game = await _load_game_full(db, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    update_data = payload.model_dump(exclude_unset=True)
    media_updates: dict[str, Any] | None = update_data.pop("media", None)

    for field, val in update_data.items():
        if hasattr(game, field):
            setattr(game, field, val)
            if field == "title" and val:
                game.pinyin_initials = generate_pinyin_initials(val)

    if media_updates:
        if not game.media:
            game.media = GameMediaPath(game_id=game.id)
        old_image_paths = {
            f: (getattr(game.media, f, "") or "").strip()
            for f in ("cover_path", "cover_thumb_path", "hero_bg_path", "logo_path", "custom_spine_path")
        }
        for m_field, m_val in media_updates.items():
            if m_val is not None and hasattr(game.media, m_field):
                setattr(game.media, m_field, m_val)
        for img_field, old_val in old_image_paths.items():
            if img_field in media_updates:
                new_val = (getattr(game.media, img_field, "") or "").strip()
                if old_val and old_val != new_val:
                    invalidate_thumbnails_for_path(old_val)

        # 保持 pv_url_or_path / pv_remote_url / pv_mode 一致性（兼容旧表单仅传 pv_url_or_path）
        if "pv_url_or_path" in media_updates and media_updates["pv_url_or_path"] is not None:
            pv_val = str(media_updates["pv_url_or_path"]).strip()
            if not pv_val:
                if "pv_remote_url" not in media_updates:
                    game.media.pv_remote_url = ""
                if "pv_mode" not in media_updates:
                    game.media.pv_mode = "none"
            elif pv_val.lower().startswith(("http://", "https://")):
                if "pv_remote_url" not in media_updates:
                    game.media.pv_remote_url = pv_val
                if "pv_mode" not in media_updates:
                    game.media.pv_mode = "link_only"
            elif "pv_mode" not in media_updates:
                game.media.pv_mode = "download"

        if "bgm_path" in media_updates and media_updates["bgm_path"] is not None:
            bgm_val = str(media_updates["bgm_path"]).strip()
            if not bgm_val:
                if "bgm_remote_url" not in media_updates:
                    game.media.bgm_remote_url = ""
                if "bgm_mode" not in media_updates:
                    game.media.bgm_mode = "none"
            elif bgm_val.lower().startswith(("http://", "https://")):
                if "bgm_remote_url" not in media_updates:
                    game.media.bgm_remote_url = bgm_val
                if "bgm_mode" not in media_updates:
                    game.media.bgm_mode = "link_only"
            elif "bgm_mode" not in media_updates:
                game.media.bgm_mode = "download"

    await db.commit()
    refreshed = await _load_game_full(db, game_id)
    assert refreshed is not None
    return refreshed


@router.delete("/{game_id}")
async def delete_game(game_id: int, db: AsyncSession = Depends(get_db)):
    game = await db.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    # 如果待删除游戏刚好处于运行追踪状态，先停止追踪
    status = process_tracker.get_status()
    if status.get("running") and status.get("game_id") == game_id:
        await process_tracker.stop_tracking(terminate_process=False)

    await db.execute(delete(CollectionGame).where(CollectionGame.game_id == game_id))
    await db.delete(game)
    await db.commit()

    invalidate_thumbnails_for_game(game_id)
    asset_folder = ASSETS_DIR / str(game_id)
    if asset_folder.exists():
        shutil.rmtree(asset_folder, ignore_errors=True)

    return {"status": "deleted", "game_id": game_id}


@router.post("/{game_id}/launch")
async def launch_game(game_id: int, db: AsyncSession = Depends(get_db)):
    """触发启动游戏并接入 ProcessTracker 防止多开与精确计时"""
    if process_tracker.is_running:
        current = process_tracker.get_status()
        raise HTTPException(
            status_code=409,
            detail=f"《{current['title']}》正在运行中，请先结束当前游戏以防多开",
        )

    game = await _load_game_full(db, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    le_setting = await db.get(AppStateSetting, "le_exe_path")
    le_path = le_setting.value if le_setting and isinstance(le_setting.value, str) else ""

    exe_path = game.media.exe_path if game.media else ""
    launch_mode = game.media.launch_mode if game.media else "direct"
    launch_args = game.media.launch_args if game.media else ""

    try:
        launch_info = os_adapter.launch_executable(
            exe_path=exe_path,
            launch_mode=launch_mode,
            launch_args=launch_args,
            le_exe_path=le_path,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"启动进程失败: {exc}")

    await _set_last_active_game(db, game.id)
    if not game.play_record:
        game.play_record = PlayRecord(game_id=game.id, total_seconds=0)
    game.play_record.last_played_at = datetime.now()
    if game.status == "todo":
        game.status = "playing"
    base_total = game.play_record.total_seconds
    await db.commit()

    tracker_status = await process_tracker.start_tracking(
        game_id=game.id,
        title=game.title,
        pid=int(launch_info.get("pid") or 0),
        exe_path=exe_path,
        is_mock=(launch_info.get("status") == "mock_started"),
        base_total_seconds=base_total,
    )

    return {
        "game_id": game.id,
        "title": game.title,
        **launch_info,
        "tracker": tracker_status,
    }


@router.post("/{game_id}/record-session")
async def record_play_session(
    game_id: int,
    duration_seconds: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    """手动补录单次游玩时长并写入历史明细"""
    stmt = (
        select(Game)
        .where(Game.id == game_id)
        .options(selectinload(Game.play_record))
    )
    game = (await db.execute(stmt)).scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    if not game.play_record:
        game.play_record = PlayRecord(game_id=game.id, total_seconds=0)

    game.play_record.total_seconds += duration_seconds
    game.play_record.last_played_at = datetime.now()
    db.add(PlaySession(game_id=game.id, duration_seconds=duration_seconds))
    await db.commit()

    return {"game_id": game.id, "total_seconds": game.play_record.total_seconds}


@router.get("/{game_id}/sessions", response_model=list[PlaySessionOut])
async def list_play_sessions(
    game_id: int,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取某游戏最近的单次游玩记录明细"""
    stmt = (
        select(PlaySession)
        .where(PlaySession.game_id == game_id)
        .order_by(PlaySession.started_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/{game_id}/sync/bangumi")
async def sync_game_status_to_bangumi(
    game_id: int,
    payload: BangumiSyncRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    单作手动单向推送游玩状态至 Bangumi（本地 → Bangumi）：
    - 若请求体传入 bangumi_id，自动持久化绑定后再推送
    - 严格校验 bangumi_token 与 bangumi_id（缺失 bangumi_id 时返回 400 及 code='MISSING_BANGUMI_ID'）
    """
    game = await _load_game_full(db, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    # 1. 若传入了 bangumi_id，立即持久化保存
    incoming_bgm_id = (payload.bangumi_id or "").strip() if payload else ""
    if incoming_bgm_id:
        game.bangumi_id = incoming_bgm_id
        merged_ext = dict(game.external_ids or {})
        if not merged_ext.get("bgm"):
            merged_ext["bgm"] = incoming_bgm_id
            game.external_ids = merged_ext
        await db.commit()

    # 2. 解析当前有效的 bangumi_id（若此前仅保存在 external_ids 中，自动补齐到列）
    resolved_bgm_id = (
        (game.bangumi_id or "").strip()
        or str((game.external_ids or {}).get("bgm") or (game.external_ids or {}).get("bangumi") or "").strip()
    )
    if resolved_bgm_id and not game.bangumi_id:
        game.bangumi_id = resolved_bgm_id
        await db.commit()

    # 3. 读取全局代理与 Bangumi Token
    rows = (await db.execute(select(AppStateSetting))).scalars().all()
    cfg = {**DEFAULT_SETTINGS, **{row.key: row.value for row in rows}}
    proxy_url = str(cfg.get("proxy_url") or "")
    token = resolve_bangumi_token(cfg)

    if not token:
        return JSONResponse(
            status_code=400,
            content={
                "code": "MISSING_BANGUMI_TOKEN",
                "detail": "请先在全局设置中填写 Bangumi Access Token",
            },
        )

    if not resolved_bgm_id:
        return JSONResponse(
            status_code=400,
            content={
                "code": "MISSING_BANGUMI_ID",
                "detail": "当前游戏尚未绑定 Bangumi 条目 ID，请先搜索绑定",
            },
        )

    if not resolved_bgm_id.isdigit():
        return JSONResponse(
            status_code=400,
            content={
                "code": "INVALID_BANGUMI_ID",
                "detail": f"无效的 Bangumi 条目 ID: {resolved_bgm_id}",
            },
        )

    local_status = (game.status or "todo").strip().lower()
    mapped_type, mapped_label = BANGUMI_COLLECTION_TYPE_MAP.get(local_status, (1, "想玩"))

    headers = {
        "User-Agent": BANGUMI_USER_AGENT,
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    url = f"{BGM_BASE_URL}/v0/users/-/collections/{resolved_bgm_id}"

    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            proxy=proxy_url or None,
        ) as client:
            resp = await client.post(url, json={"type": mapped_type})
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"连接 Bangumi 推送接口失败: {exc}")

    if resp.status_code in (401, 403):
        raise HTTPException(status_code=401, detail="Bangumi Access Token 无效或已过期")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Bangumi 上未找到对应的条目 ID")
    if resp.status_code not in (200, 202, 204):
        raise HTTPException(
            status_code=502,
            detail=f"Bangumi 推送失败 (HTTP {resp.status_code})",
        )

    return {
        "synced": True,
        "bangumi_id": resolved_bgm_id,
        "local_status": game.status,
        "bangumi_type": mapped_type,
        "bangumi_type_label": mapped_label,
    }
