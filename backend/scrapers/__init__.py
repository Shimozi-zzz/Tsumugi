from backend.scrapers.bangumi import BangumiScraper
from backend.scrapers.base import (
    BaseScraper,
    ScrapedGameItem,
    ScraperGameDetail,
    ScraperSearchResult,
)
from backend.scrapers.dlsite import DLsiteScraper
from backend.scrapers.igdb import IGDBScraper
from backend.scrapers.kungal import KungalScraper
from backend.scrapers.manager import (
    ScraperManager,
    rerank_results,
    score_search_result,
)
from backend.scrapers.steam import SteamScraper
from backend.scrapers.steamgriddb import SteamGridDBScraper
from backend.scrapers.touchgal import TouchGalScraper
from backend.scrapers.vndb import VNDBScraper
from backend.scrapers.ymgal import YMGalScraper

__all__ = [
    "BaseScraper",
    "ScrapedGameItem",
    "ScraperSearchResult",
    "ScraperGameDetail",
    "ScraperManager",
    "score_search_result",
    "rerank_results",
    "KungalScraper",
    "YMGalScraper",
    "DLsiteScraper",
    "VNDBScraper",
    "BangumiScraper",
    "SteamScraper",
    "SteamGridDBScraper",
    "IGDBScraper",
    "TouchGalScraper",
]
