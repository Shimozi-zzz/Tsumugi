from __future__ import annotations

from backend.services.importers.base import (
    BaseLibraryImporter,
    DetectResult,
    DuplicateStrategy,
    ExternalGameCandidate,
    ExternalSourceApp,
    ImportErrorItem,
    ImporterError,
    ImportSummary,
)
from backend.services.importers.executor import annotate_existing_games, execute_external_import
from backend.services.importers.playnite import PlayniteImporter
from backend.services.importers.vnite import VniteImporter

IMPORTER_REGISTRY: dict[ExternalSourceApp, type[BaseLibraryImporter]] = {
    "playnite": PlayniteImporter,
    "vnite": VniteImporter,
}


def get_importer(source: ExternalSourceApp) -> BaseLibraryImporter:
    cls = IMPORTER_REGISTRY.get(source)
    if cls is None:
        raise ImporterError(f"不支持的外部游戏库来源: {source}")
    return cls()


__all__ = [
    "BaseLibraryImporter",
    "DetectResult",
    "DuplicateStrategy",
    "ExternalGameCandidate",
    "ExternalSourceApp",
    "IMPORTER_REGISTRY",
    "ImportErrorItem",
    "ImportSummary",
    "ImporterError",
    "PlayniteImporter",
    "VniteImporter",
    "annotate_existing_games",
    "execute_external_import",
    "get_importer",
]
