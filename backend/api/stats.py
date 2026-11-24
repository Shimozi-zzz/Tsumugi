from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.database import get_db
from backend.db.models import CollectionItem, Game, PlaySession

router = APIRouter(prefix="/api/stats", tags=["Stats"])


def _compute_streaks(active_dates: set[date], today: date) -> tuple[int, int]:
    """计算最长连续游玩天数 (longest_streak) 与当前连续天数 (current_streak)"""
    if not active_dates:
        return 0, 0

    sorted_days = sorted(active_dates)
    longest = 1
    run = 1
    for i in range(1, len(sorted_days)):
        if (sorted_days[i] - sorted_days[i - 1]).days == 1:
            run += 1
            if run > longest:
                longest = run
        else:
            run = 1

    current = 0
    cursor = today if today in active_dates else (today - timedelta(days=1))
    while cursor in active_dates:
        current += 1
        cursor -= timedelta(days=1)

    return longest, current


def _last_n_months(today: date, count: int = 12) -> list[str]:
    year = today.year
    month = today.month
    months: list[str] = []
    for _ in range(count):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    months.reverse()
    return months


@router.get("/ledger")
async def get_time_ledger(
    days: int = Query(365, ge=30, le=730, description="热力图回溯天数"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """聚合输出游玩热力图与时间账本数据"""
    games_stmt = select(Game).options(
        selectinload(Game.media),
        selectinload(Game.play_record),
    )
    games = list((await db.execute(games_stmt)).scalars().all())
    game_map: dict[int, Game] = {g.id: g for g in games}

    sessions_stmt = select(PlaySession).order_by(PlaySession.started_at.desc())
    sessions = list((await db.execute(sessions_stmt)).scalars().all())

    today = date.today()
    cutoff_date = today - timedelta(days=days - 1)
    months_keys = _last_n_months(today, 12)
    monthly_totals: dict[str, int] = {m: 0 for m in months_keys}
    monthly_counts: dict[str, int] = {m: 0 for m in months_keys}

    # 按日期聚合热力图 & 活跃天集合
    all_active_dates: set[date] = set()
    heatmap_day_totals: dict[str, int] = defaultdict(int)
    heatmap_day_sessions: dict[str, int] = defaultdict(int)
    heatmap_day_games: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    # 每个游戏的初见时间与会话次数
    game_first_played: dict[int, datetime] = {}
    game_session_count: dict[int, int] = defaultdict(int)

    for s in sessions:
        dur = max(0, int(s.duration_seconds or 0))
        started = s.started_at
        if started is None:
            continue

        game_session_count[s.game_id] += 1
        prev_first = game_first_played.get(s.game_id)
        if prev_first is None or started < prev_first:
            game_first_played[s.game_id] = started

        if dur <= 0:
            continue

        d = started.date()
        all_active_dates.add(d)

        if d >= cutoff_date:
            d_key = d.isoformat()
            heatmap_day_totals[d_key] += dur
            heatmap_day_sessions[d_key] += 1
            heatmap_day_games[d_key][s.game_id] += dur

        m_key = f"{d.year:04d}-{d.month:02d}"
        if m_key in monthly_totals:
            monthly_totals[m_key] += dur
            monthly_counts[m_key] += 1

    longest_streak, current_streak = _compute_streaks(all_active_dates, today)

    total_seconds_from_records = sum(
        int(g.play_record.total_seconds or 0) for g in games if g.play_record
    )
    total_seconds_from_sessions = sum(max(0, int(s.duration_seconds or 0)) for s in sessions)
    total_seconds = max(total_seconds_from_records, total_seconds_from_sessions)

    done_games = sum(1 for g in games if g.status == "done")
    playing_games = sum(1 for g in games if g.status == "playing")

    # 组装热力图每日条目
    heatmap: list[dict[str, Any]] = []
    for d_key in sorted(heatmap_day_totals.keys()):
        day_game_items = []
        for gid, g_dur in sorted(
            heatmap_day_games[d_key].items(), key=lambda kv: kv[1], reverse=True
        ):
            g = game_map.get(gid)
            day_game_items.append(
                {
                    "game_id": gid,
                    "title": g.title if g else f"游戏 #{gid}",
                    "duration_seconds": g_dur,
                }
            )
        heatmap.append(
            {
                "date": d_key,
                "total_seconds": heatmap_day_totals[d_key],
                "sessions_count": heatmap_day_sessions[d_key],
                "games": day_game_items,
            }
        )

    monthly = [
        {
            "month": m_key,
            "total_seconds": monthly_totals[m_key],
            "sessions_count": monthly_counts[m_key],
        }
        for m_key in months_keys
    ]

    # 作品时长榜
    ranked_games = sorted(
        games,
        key=lambda g: int(g.play_record.total_seconds or 0) if g.play_record else 0,
        reverse=True,
    )
    top_games: list[dict[str, Any]] = []
    for g in ranked_games:
        sec = int(g.play_record.total_seconds or 0) if g.play_record else 0
        if sec <= 0 and game_session_count.get(g.id, 0) == 0:
            continue
        first_dt = game_first_played.get(g.id)
        last_dt = g.play_record.last_played_at if g.play_record else None
        cover_thumb = ""
        if g.media:
            cover_thumb = g.media.cover_thumb_path or g.media.cover_path or ""
        top_games.append(
            {
                "game_id": g.id,
                "title": g.title,
                "developer": g.developer,
                "status": g.status,
                "is_nsfw": bool(g.is_nsfw),
                "cover_thumb_path": cover_thumb,
                "total_seconds": sec,
                "session_count": game_session_count.get(g.id, 0),
                "first_played_at": first_dt.isoformat() if first_dt else None,
                "last_played_at": last_dt.isoformat() if last_dt else None,
            }
        )
        if len(top_games) >= 15:
            break

    # 最近 30 条游玩流水
    recent_sessions: list[dict[str, Any]] = []
    for s in sessions[:30]:
        g = game_map.get(s.game_id)
        cover_thumb = ""
        if g and g.media:
            cover_thumb = g.media.cover_thumb_path or g.media.cover_path or ""
        recent_sessions.append(
            {
                "id": s.id,
                "game_id": s.game_id,
                "title": g.title if g else f"游戏 #{s.game_id}",
                "is_nsfw": bool(g.is_nsfw) if g else False,
                "cover_thumb_path": cover_thumb,
                "started_at": s.started_at.isoformat() if s.started_at else "",
                "duration_seconds": max(0, int(s.duration_seconds or 0)),
            }
        )

    return {
        "days": days,
        "summary": {
            "total_seconds": total_seconds,
            "total_sessions": len(sessions),
            "total_games": len(games),
            "done_games": done_games,
            "playing_games": playing_games,
            "active_days": len(all_active_dates),
            "longest_streak": longest_streak,
            "current_streak": current_streak,
        },
        "heatmap": heatmap,
        "monthly": monthly,
        "top_games": top_games,
        "recent_sessions": recent_sessions,
    }


@router.get("/collage")
async def get_journey_collage(
    year: str = Query("all", description="统计范围：all 或四位年份（如 2026）"),
    collection_id: int | None = Query(None, description="可选自定义分组 ID 过滤"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """为前端「游戏历程拼图」提供按游玩时长汇总的作品元数据与封面/Hero 路径"""
    raw_year = (year or "all").strip()
    target_year: int | None = None
    normalized_year = "all"
    if raw_year.lower() != "all" and len(raw_year) == 4 and raw_year.isdigit():
        target_year = int(raw_year)
        normalized_year = raw_year

    # 读取所有会话，用于提取可用年份列表及特定年份的时长聚合
    sessions_stmt = select(PlaySession.game_id, PlaySession.started_at, PlaySession.duration_seconds)
    session_rows = (await db.execute(sessions_stmt)).all()

    years_set: set[str] = set()
    year_seconds_by_game: dict[int, int] = defaultdict(int)
    all_session_seconds_by_game: dict[int, int] = defaultdict(int)

    for game_id, started_at, duration_seconds in session_rows:
        dur = max(0, int(duration_seconds or 0))
        if started_at is not None:
            years_set.add(f"{started_at.year:04d}")
            if target_year is not None and started_at.year == target_year:
                year_seconds_by_game[game_id] += dur
        if dur > 0:
            all_session_seconds_by_game[game_id] += dur

    available_years = sorted(years_set, reverse=True)

    # 查询作品集合（可选按自定义分组过滤）
    games_stmt = select(Game).options(
        selectinload(Game.media),
        selectinload(Game.play_record),
    )
    if collection_id is not None:
        cg_stmt = (
            select(CollectionItem.game_id)
            .where(CollectionItem.collection_id == collection_id)
            .order_by(CollectionItem.position.asc(), CollectionItem.id.asc())
        )
        allowed_ids = list((await db.execute(cg_stmt)).scalars().all())
        if not allowed_ids:
            return {
                "year": normalized_year,
                "available_years": available_years,
                "total_seconds": 0,
                "played_games_count": 0,
                "total_games_count": 0,
                "items": [],
            }
        games_stmt = games_stmt.where(Game.id.in_(allowed_ids))

    games = list((await db.execute(games_stmt)).scalars().all())

    items: list[dict[str, Any]] = []
    for g in games:
        if target_year is None:
            record_sec = int(g.play_record.total_seconds or 0) if g.play_record else 0
            play_seconds = record_sec if record_sec > 0 else all_session_seconds_by_game.get(g.id, 0)
        else:
            play_seconds = year_seconds_by_game.get(g.id, 0)

        items.append(
            {
                "id": g.id,
                "title": g.title,
                "sub_title": g.sub_title or "",
                "play_seconds": play_seconds,
                "status": g.status or "todo",
                "is_nsfw": bool(g.is_nsfw),
                "cover_path": (g.media.cover_path or "") if g.media else "",
                "cover_thumb_path": (g.media.cover_thumb_path or "") if g.media else "",
                "hero_bg_path": (g.media.hero_bg_path or "") if g.media else "",
            }
        )

    items.sort(key=lambda item: (-item["play_seconds"], item["title"].lower()))

    total_seconds = sum(item["play_seconds"] for item in items)
    played_games_count = sum(1 for item in items if item["play_seconds"] > 0)

    return {
        "year": normalized_year,
        "available_years": available_years,
        "total_seconds": total_seconds,
        "played_games_count": played_games_count,
        "total_games_count": len(items),
        "items": items,
    }
