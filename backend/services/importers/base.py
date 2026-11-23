from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ExternalSourceApp = Literal["playnite", "vnite"]
DuplicateStrategy = Literal["skip", "merge_playtime"]


class ImporterError(ValueError):
    """外部游戏库导入器的可控业务异常（用于向前端返回清晰友好的提示）"""


class ExternalGameCandidate(BaseModel):
    """外部游戏库扫描产出的统一中间候选模型"""

    external_id: str
    source_app: ExternalSourceApp
    name: str
    original_name: str = ""
    description: str = ""
    release_date: str = ""
    developers: list[str] = Field(default_factory=list)
    publishers: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    playtime_seconds: int = 0
    last_played_at: datetime | None = None
    play_status: str = "todo"
    platform_source: str = ""
    steam_appid: str = ""
    vndb_id: str = ""
    bangumi_id: str = ""
    ymgal_id: str = ""
    install_dir: str = ""
    executable_path: str = ""
    cover_path: str = ""
    background_path: str = ""
    exists_in_tsumugi: bool = False
    existing_game_id: int | None = None


class DetectResult(BaseModel):
    """本地外部游戏库路径自动探测结果"""

    source: ExternalSourceApp
    detected_path: str = ""
    valid: bool = False
    message: str = ""
    candidates: list[str] = Field(default_factory=list)


class ImportErrorItem(BaseModel):
    external_id: str = ""
    name: str = ""
    error: str


class ImportSummary(BaseModel):
    """外部库导入执行结果汇总"""

    imported: int = 0
    merged: int = 0
    skipped: int = 0
    errors: list[ImportErrorItem] = Field(default_factory=list)
    imported_ids: list[int] = Field(default_factory=list)
    merged_ids: list[int] = Field(default_factory=list)


class BaseLibraryImporter(ABC):
    """外部游戏库适配器抽象基类"""

    source_name: ExternalSourceApp

    @abstractmethod
    def detect_path(self) -> DetectResult:
        """自动探测本地外部软件的数据目录及有效性"""
        raise NotImplementedError

    @abstractmethod
    def scan(self, path: str) -> list[ExternalGameCandidate]:
        """扫描指定路径或备份文件并返回标准化候选游戏列表"""
        raise NotImplementedError
