from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.database import get_db
from backend.db.models import Game
from backend.services.backup_service import create_auto_snapshot
from backend.services.importers import (
    DuplicateStrategy,
    ExternalSourceApp,
    ImporterError,
    annotate_existing_games,
    execute_external_import,
    get_importer,
)

logger = logging.getLogger("tsumugi.api.import_external")
router = APIRouter(prefix="/api/import/external", tags=["ExternalImport"])


class ExternalScanRequest(BaseModel):
    path: str = Field(..., min_length=1, description="外部游戏库目录或备份文件路径")


class ExternalExecuteRequest(BaseModel):
    path: str = Field(..., min_length=1, description="外部游戏库目录或备份文件路径")
    selected_ids: list[str] = Field(default_factory=list, description="勾选导入的 external_id 列表")
    duplicate_strategy: DuplicateStrategy = Field(
        default="skip",
        description="重复条目处理策略：skip（跳过已存在）或 merge_playtime（合并游玩时长）",
    )


@router.get("/{source}/detect")
async def detect_external_library(source: ExternalSourceApp) -> dict[str, Any]:
    """自动探测本地外部游戏库路径及有效性（未安装时统一返回 HTTP 200 及中性提示）"""
    importer = get_importer(source)
    result = await asyncio.to_thread(importer.detect_path)
    if result.valid and result.detected_path:
        return {
            **result.model_dump(),
            "found": True,
            "path": result.detected_path,
        }
    return {
        "source": source,
        "found": False,
        "path": "",
        "detected_path": "",
        "valid": False,
        "message": "未自动检测到默认路径，请手动输入路径或选择目录",
        "candidates": result.candidates,
    }


@router.post("/{source}/scan")
async def scan_external_library(
    source: ExternalSourceApp,
    payload: ExternalScanRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """扫描外部游戏库，返回标准化候选列表及去重统计（总数、新增数、已存在数）"""
    importer = get_importer(source)
    try:
        candidates = await asyncio.to_thread(importer.scan, payload.path)
    except (ImporterError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    stmt = select(Game).options(selectinload(Game.media), selectinload(Game.play_record))
    existing_games = list((await db.execute(stmt)).scalars().all())
    annotate_existing_games(candidates, existing_games)

    total_count = len(candidates)
    existing_count = sum(1 for c in candidates if c.exists_in_tsumugi)
    new_count = total_count - existing_count

    return {
        "source": source,
        "path": payload.path.strip(),
        "stats": {
            "total": total_count,
            "new": new_count,
            "existing": existing_count,
        },
        "items": [c.model_dump(mode="json") for c in candidates],
    }


@router.post("/{source}/execute")
async def execute_external_library_import(
    source: ExternalSourceApp,
    payload: ExternalExecuteRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """执行外部游戏库入库、去重合并与本地视觉资产独立拷贝"""
    importer = get_importer(source)
    try:
        candidates = await asyncio.to_thread(importer.scan, payload.path)
    except (ImporterError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    selected_set = {str(x).strip() for x in payload.selected_ids if str(x).strip()}
    if not selected_set:
        return {
            "source": source,
            "imported": 0,
            "merged": 0,
            "skipped": 0,
            "errors": [],
            "imported_ids": [],
            "merged_ids": [],
        }

    chosen = [c for c in candidates if c.external_id in selected_set]
    if chosen:
        try:
            await asyncio.to_thread(create_auto_snapshot, tag="pre_import", force=True)
        except Exception as exc:
            logger.warning("Pre-import safety snapshot skipped: %s", exc)

    summary = await execute_external_import(
        db=db,
        candidates=chosen,
        duplicate_strategy=payload.duplicate_strategy,
    )
    return {
        "source": source,
        **summary.model_dump(),
    }
