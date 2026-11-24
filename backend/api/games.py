import json
import math
import re
import shutil
from datetime import datetime
from typing import Any, Literal
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.api.collections import serialize_game_collections
from backend.api.settings import DEFAULT_SETTINGS, resolve_bangumi_token
from backend.core.config import ASSETS_DIR
from backend.core.os_adapter import os_adapter
from backend.db.database import get_db
from backend.db.models import (
    AppStateSetting,
    CollectionItem,
    Game,
    GameMediaPath,
    GameNote,
    PlayRecord,
    PlaySession,
)
from backend.schemas import (
    BangumiSyncRequest,
    GameCollectionMembership,
    GameCreate,
    GameNoteCreate,
    GameNoteOut,
    GameNoteUpdate,
    GameOut,
    GameRatingUpdate,
    GameUpdate,
    PlaySessionOut,
)
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

STATUS_LABEL_ZH: dict[str, str] = {
    "todo": "未开始",
    "unplayed": "未开始",
    "playing": "攻略中",
    "done": "已通关",
    "completed": "已通关",
}

RATING_DIMENSION_META: tuple[tuple[str, str], ...] = (
    ("story", "剧本"),
    ("visual", "美术与演出"),
    ("music", "音乐"),
    ("atmosphere", "氛围与体验"),
)
VALID_RATING_DIMENSIONS: frozenset[str] = frozenset(k for k, _ in RATING_DIMENSION_META)

NOTE_TYPE_LABELS: dict[str, str] = {
    "work": "作品总评",
    "character": "角色手记",
    "misc": "随记",
}

_FILENAME_UNSAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')

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


async def _serialize_game_detail(db: AsyncSession, game: Game) -> GameOut:
    """序列化单部游戏详情，附带手记数与所属系列合集（含同系列按 position 排好序的作品摘要）"""
    notes_count = int(
        (
            await db.execute(
                select(func.count(GameNote.id)).where(GameNote.game_id == game.id)
            )
        ).scalar()
        or 0
    )
    collections_data = [
        GameCollectionMembership.model_validate(m)
        for m in await serialize_game_collections(db, game.id)
    ]
    base = GameOut.model_validate(game)
    return base.model_copy(
        update={
            "notes_count": notes_count,
            "collections": collections_data,
        }
    )


def _yaml_scalar(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _sanitize_export_filename(name: str, fallback: str = "tsumugi-notes") -> str:
    cleaned = _FILENAME_UNSAFE_RE.sub("_", (name or "").strip()).strip(". _")
    return (cleaned[:80] if cleaned else fallback)


def _build_notes_markdown_export(
    game: Game,
    notes: list[GameNote],
    collection_names: list[str],
) -> str:
    """拼装含标准 YAML Frontmatter 的结构化 Markdown 文档（兼容 Obsidian / Typora 等工具）"""
    total_seconds = int(game.play_record.total_seconds or 0) if game.play_record else 0
    play_hours = round(total_seconds / 3600.0, 1)
    status_zh = STATUS_LABEL_ZH.get((game.status or "todo").strip().lower(), game.status or "未开始")
    exported_at = datetime.now().replace(microsecond=0).isoformat()

    fm: list[str] = ["---"]
    fm.append(f"title: {_yaml_scalar(game.title)}")
    if (game.sub_title or "").strip():
        fm.append(f"original_title: {_yaml_scalar(game.sub_title.strip())}")
    if (game.developer or "").strip():
        fm.append(f"developer: {_yaml_scalar(game.developer.strip())}")
    if (game.publisher or "").strip():
        fm.append(f"publisher: {_yaml_scalar(game.publisher.strip())}")
    if (game.release_date or "").strip():
        fm.append(f"release_date: {_yaml_scalar(game.release_date.strip())}")
    fm.append(f"status: {_yaml_scalar(status_zh)}")
    fm.append(f"play_time_hours: {play_hours}")

    if game.rating_overall is not None:
        fm.append(f"rating_overall: {round(float(game.rating_overall), 1)}")

    dims = game.rating_dimensions if isinstance(game.rating_dimensions, dict) else {}
    present_dims = [
        (key, round(float(dims[key]), 1))
        for key, _ in RATING_DIMENSION_META
        if key in dims and dims[key] is not None
    ]
    if present_dims:
        fm.append("ratings:")
        for key, val in present_dims:
            fm.append(f"  {key}: {val}")

    short_review = (game.short_review or "").strip()
    if short_review:
        fm.append(f"short_review: {_yaml_scalar(short_review)}")

    tags = [str(t).strip() for t in (game.tags or []) if str(t).strip()]
    if tags:
        fm.append("tags:")
        for tag in tags:
            fm.append(f"  - {_yaml_scalar(tag)}")

    if collection_names:
        fm.append("collections:")
        for cname in collection_names:
            fm.append(f"  - {_yaml_scalar(cname)}")

    fm.append(f"exported_at: {_yaml_scalar(exported_at)}")
    fm.append("---")

    body: list[str] = [f"# {game.title}"]
    if (game.sub_title or "").strip():
        body.append(f"*{game.sub_title.strip()}*")

    if short_review:
        body.append(f"> {short_review}")

    # 基础档案与游玩概况
    meta_lines: list[str] = []
    if (game.developer or "").strip():
        meta_lines.append(f"- **开发商**：{game.developer.strip()}")
    if (game.release_date or "").strip():
        meta_lines.append(f"- **发售日期**：{game.release_date.strip()}")
    meta_lines.append(f"- **攻略状态**：{status_zh}")
    meta_lines.append(f"- **累计游玩**：{play_hours} 小时")
    if meta_lines:
        body.append("## 作品档案\n\n" + "\n".join(meta_lines))

    # 多维评分
    if game.rating_overall is not None or present_dims:
        rating_lines: list[str] = []
        if game.rating_overall is not None:
            rating_lines.append(f"- **综合评分**：{round(float(game.rating_overall), 1)} / 10")
        dim_label_map = dict(RATING_DIMENSION_META)
        for key, val in present_dims:
            rating_lines.append(f"- **{dim_label_map.get(key, key)}**：{val} / 10")
        body.append("## 多维评分\n\n" + "\n".join(rating_lines))

    # 手记正文
    if notes:
        note_sections: list[str] = []
        for note in notes:
            type_label = NOTE_TYPE_LABELS.get(note.note_type, "手记")
            heading = f"### [{type_label}] {note.title or type_label}"
            updated_str = (
                note.updated_at.strftime("%Y-%m-%d %H:%M")
                if note.updated_at
                else ""
            )
            parts = [heading]
            if updated_str:
                parts.append(f"*更新于 {updated_str}*")
            content_text = (note.content_md or "").strip()
            if content_text:
                parts.append(content_text)
            note_sections.append("\n\n".join(parts))
        body.append("## 手记\n\n" + "\n\n---\n\n".join(note_sections))

    return "\n".join(fm) + "\n\n" + "\n\n".join(body).rstrip() + "\n"


@router.get("", response_model=list[GameOut])
async def list_games(
    status: str | None = Query(
        None, description="按状态筛选: unplayed / todo / playing / completed / done"
    ),
    collection_id: int | None = Query(None, description="按系列合集/分组 ID 筛选"),
    tag: str | None = Query(None, description="按标签筛选"),
    q: str | None = Query(None, description="按标题、原名、开发者、发行商、拼音首字母模糊搜索"),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Game).options(selectinload(Game.media), selectinload(Game.play_record))
    if collection_id is not None:
        stmt = (
            stmt.join(CollectionItem, CollectionItem.game_id == Game.id)
            .where(CollectionItem.collection_id == collection_id)
            .order_by(CollectionItem.position.asc(), Game.id.asc())
        )
    else:
        stmt = stmt.order_by(Game.id.asc())

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

    if not games:
        return []

    game_ids = [g.id for g in games]
    note_counts_rows = (
        await db.execute(
            select(GameNote.game_id, func.count(GameNote.id))
            .where(GameNote.game_id.in_(game_ids))
            .group_by(GameNote.game_id)
        )
    ).all()
    notes_count_map = {int(gid): int(cnt) for gid, cnt in note_counts_rows}

    return [
        GameOut.model_validate(g).model_copy(
            update={"notes_count": notes_count_map.get(g.id, 0)}
        )
        for g in games
    ]


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
    return await _serialize_game_detail(db, game)


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
    return await _serialize_game_detail(db, refreshed)


@router.put("/{game_id}/rating", response_model=GameOut)
async def update_game_rating(
    game_id: int,
    payload: GameRatingUpdate,
    db: AsyncSession = Depends(get_db),
):
    """保存或清空作品多维评分、综合评分与一句话短评（未手填综合分时自动计算各维度均值并保留 1 位小数）"""
    game = await _load_game_full(db, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    if payload.clear:
        game.rating_overall = None
        game.rating_dimensions = None
        if payload.short_review is not None:
            game.short_review = payload.short_review.strip()
        else:
            game.short_review = ""
    else:
        clean_dims: dict[str, float] = {}
        if payload.rating_dimensions is not None:
            for key, raw_val in payload.rating_dimensions.items():
                if key not in VALID_RATING_DIMENSIONS:
                    raise HTTPException(status_code=400, detail=f"未知评分维度: {key}")
                if raw_val is None:
                    continue
                val = float(raw_val)
                if val < 1.0 or val > 10.0:
                    raise HTTPException(status_code=400, detail=f"维度 {key} 评分必须在 1.0~10.0 之间")
                clean_dims[key] = round(val * 2.0) / 2.0
            game.rating_dimensions = clean_dims or None
        else:
            existing_dims = game.rating_dimensions if isinstance(game.rating_dimensions, dict) else {}
            clean_dims = {
                k: float(v)
                for k, v in existing_dims.items()
                if k in VALID_RATING_DIMENSIONS and v is not None
            }

        if payload.rating_overall is not None:
            game.rating_overall = round(float(payload.rating_overall), 1)
        elif clean_dims:
            game.rating_overall = round(sum(clean_dims.values()) / len(clean_dims), 1)
        else:
            game.rating_overall = None

        if payload.short_review is not None:
            game.short_review = payload.short_review.strip()

    await db.commit()
    refreshed = await _load_game_full(db, game_id)
    assert refreshed is not None
    return await _serialize_game_detail(db, refreshed)


@router.get("/{game_id}/notes", response_model=list[GameNoteOut])
async def list_game_notes(
    game_id: int,
    note_type: Literal["work", "character", "misc"] | None = Query(
        None, description="可选：按手记类型筛选 work / character / misc"
    ),
    db: AsyncSession = Depends(get_db),
):
    """获取作品下的全部长评手记（置顶优先，其次按更新时间倒序）"""
    exists = await db.get(Game, game_id)
    if not exists:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    stmt = select(GameNote).where(GameNote.game_id == game_id)
    if note_type:
        stmt = stmt.where(GameNote.note_type == note_type)
    stmt = stmt.order_by(GameNote.is_pinned.desc(), GameNote.updated_at.desc(), GameNote.id.desc())
    return list((await db.execute(stmt)).scalars().all())


@router.get("/{game_id}/notes/export")
async def export_game_notes_markdown(
    game_id: int,
    note_id: int | None = Query(None, description="可选：仅导出指定单篇手记"),
    db: AsyncSession = Depends(get_db),
):
    """将作品元数据、游玩时长、多维评分、短评与手记导出为含标准 YAML Frontmatter 的 Markdown 文件"""
    game = await _load_game_full(db, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    if note_id is not None:
        single_note = (
            await db.execute(
                select(GameNote).where(GameNote.id == note_id, GameNote.game_id == game_id)
            )
        ).scalar_one_or_none()
        if not single_note:
            raise HTTPException(status_code=404, detail="未找到指定手记")
        notes = [single_note]
    else:
        notes = list(
            (
                await db.execute(
                    select(GameNote)
                    .where(GameNote.game_id == game_id)
                    .order_by(GameNote.is_pinned.desc(), GameNote.created_at.asc(), GameNote.id.asc())
                )
            )
            .scalars()
            .all()
        )

    memberships = await serialize_game_collections(db, game_id)
    collection_names = [m["name"] for m in memberships if m.get("name")]
    md_text = _build_notes_markdown_export(game, notes, collection_names)

    base_name = _sanitize_export_filename(
        f"{game.title}-{notes[0].title}" if (note_id is not None and notes) else f"{game.title}-手记",
        fallback=f"tsumugi-game-{game_id}",
    )
    utf8_filename = f"{base_name}.md"
    ascii_filename = f"tsumugi-game-{game_id}-notes.md"

    return Response(
        content=md_text.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_filename}"; '
                f"filename*=UTF-8''{quote(utf8_filename)}"
            )
        },
    )


@router.post("/{game_id}/notes", response_model=GameNoteOut)
async def create_game_note(
    game_id: int,
    payload: GameNoteCreate,
    db: AsyncSession = Depends(get_db),
):
    """为指定作品新建一篇长评手记（作品总评 / 角色手记 / 随记）"""
    exists = await db.get(Game, game_id)
    if not exists:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    default_title = NOTE_TYPE_LABELS.get(payload.note_type, "手记")
    title = (payload.title or "").strip() or default_title
    now = datetime.now()
    note = GameNote(
        game_id=game_id,
        note_type=payload.note_type,
        title=title,
        content_md=payload.content_md or "",
        is_pinned=bool(payload.is_pinned),
        created_at=now,
        updated_at=now,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return note


@router.patch("/{game_id}/notes/{note_id}", response_model=GameNoteOut)
async def update_game_note(
    game_id: int,
    note_id: int,
    payload: GameNoteUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新指定手记的标题、类型、正文或置顶状态"""
    note = (
        await db.execute(
            select(GameNote).where(GameNote.id == note_id, GameNote.game_id == game_id)
        )
    ).scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="未找到指定手记")

    if payload.note_type is not None:
        note.note_type = payload.note_type
    if payload.title is not None:
        cleaned_title = payload.title.strip()
        if not cleaned_title:
            raise HTTPException(status_code=400, detail="手记标题不能为空")
        note.title = cleaned_title
    if payload.content_md is not None:
        note.content_md = payload.content_md
    if payload.is_pinned is not None:
        note.is_pinned = bool(payload.is_pinned)
    note.updated_at = datetime.now()

    await db.commit()
    await db.refresh(note)
    return note


@router.delete("/{game_id}/notes/{note_id}")
async def delete_game_note(
    game_id: int,
    note_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除指定手记"""
    note = (
        await db.execute(
            select(GameNote).where(GameNote.id == note_id, GameNote.game_id == game_id)
        )
    ).scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="未找到指定手记")

    await db.delete(note)
    await db.commit()
    return {"status": "deleted", "note_id": note_id, "game_id": game_id}


@router.delete("/{game_id}")
async def delete_game(game_id: int, db: AsyncSession = Depends(get_db)):
    game = await db.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="未找到指定游戏")

    # 如果待删除游戏刚好处于运行追踪状态，先停止追踪
    status = process_tracker.get_status()
    if status.get("running") and status.get("game_id") == game_id:
        await process_tracker.stop_tracking(terminate_process=False)

    await db.execute(delete(CollectionItem).where(CollectionItem.game_id == game_id))
    await db.execute(delete(GameNote).where(GameNote.game_id == game_id))
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

    bgm_body: dict[str, Any] = {"type": mapped_type}

    sync_rating = payload.sync_rating if payload is not None else True
    explicit_rate = payload.rate if payload is not None else None
    if explicit_rate is not None:
        bgm_body["rate"] = int(explicit_rate)
    elif sync_rating and game.rating_overall is not None:
        bgm_body["rate"] = min(
            10,
            max(1, int(math.floor(float(game.rating_overall) + 0.5))),
        )

    sync_comment = payload.sync_comment if payload is not None else True
    explicit_comment = payload.comment if payload is not None else None
    if explicit_comment is not None:
        cleaned_comment = explicit_comment.strip()[:200]
        if cleaned_comment:
            bgm_body["comment"] = cleaned_comment
    elif sync_comment and (game.short_review or "").strip():
        bgm_body["comment"] = (game.short_review or "").strip()[:200]

    if payload is not None and payload.private is not None:
        bgm_body["private"] = bool(payload.private)

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
            resp = await client.post(url, json=bgm_body)
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
        "synced_rate": bgm_body.get("rate"),
        "synced_comment": bgm_body.get("comment", ""),
        "private": bgm_body.get("private"),
    }
