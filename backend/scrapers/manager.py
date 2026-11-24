from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import hashlib
import logging
import re
from typing import Any

from backend.core.scraper_settings import (
    ALL_MANAGED_SCRAPER_IDS,
    DEFAULT_KUNGAL_BASE_URL,
    FREE_SCRAPER_IDS,
    KEY_SCRAPER_IDS,
    default_scraper_settings,
    is_source_configured,
)
from backend.scrapers.bangumi import BangumiScraper
from backend.scrapers.base import (
    BaseScraper,
    SOURCE_DISPLAY_NAMES,
    ScraperGameDetail,
    ScraperSearchResult,
    canonicalize_source_name,
    extract_year,
    normalize_external_ids,
    normalize_search_text,
)
from backend.scrapers.dlsite import DLsiteScraper
from backend.scrapers.igdb import IGDBScraper
from backend.scrapers.kungal import KungalScraper
from backend.scrapers.steam import SteamScraper
from backend.scrapers.steamgriddb import SteamGridDBScraper
from backend.scrapers.touchgal import TouchGalScraper
from backend.scrapers.vndb import VNDBScraper
from backend.scrapers.ymgal import YMGalScraper

logger = logging.getLogger("tsumugi.scrapers.manager")

DEFAULT_PER_SOURCE_TIMEOUT = 8.0

# 场景预设并发优先级
CATEGORY_PRESETS: dict[str, tuple[str, ...]] = {
    "all": ("ymgal", "kungal", "touchgal", "vndb", "bangumi", "dlsite", "steam", "igdb"),
    "galgame": ("ymgal", "kungal", "touchgal", "vndb", "bangumi", "dlsite"),
    "general": ("steam", "igdb", "bangumi"),
}

# 直查检测顺序：特定域名/前缀优先，纯数字 AppID (steam) 放在最后
DIRECT_ID_CHECK_ORDER: tuple[str, ...] = (
    "kungal",
    "ymgal",
    "dlsite",
    "vndb",
    "bangumi",
    "igdb",
    "steamgriddb",
    "touchgal",
    "steam",
)

# 衍生品关键词正则（非明确搜索时自动降权）
_DERIVATIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![a-z0-9])ost(?![a-z0-9])", re.IGNORECASE),
    re.compile(r"original\s*sound\s*track", re.IGNORECASE),
    re.compile(r"(?<![a-z])sound\s*track(?![a-z])", re.IGNORECASE),
    re.compile(r"(?<![a-z])art\s*book(?![a-z])", re.IGNORECASE),
    re.compile(r"(?<![a-z])fan\s*book(?![a-z])", re.IGNORECASE),
    re.compile(r"drama\s*cd", re.IGNORECASE),
    re.compile(r"voice\s*drama", re.IGNORECASE),
    re.compile(r"vocal\s*(?:album|collection|cd)", re.IGNORECASE),
    re.compile(r"mini\s*album|bonus\s*cd|theme\s*song", re.IGNORECASE),
    re.compile(r"(?<![a-z])(?:demo|trial)(?![a-z])", re.IGNORECASE),
    re.compile(
        r"设定集|设定资料集|画集|原画集|公式设定|原声集|原声带|原声大碟|音乐集|角色歌|"
        r"广播剧|音频剧|体验版|体験版|试玩版|攻略本|サントラ|サウンドトラック|ドラマcd|ビジュアルファンブック",
        re.IGNORECASE,
    ),
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_PURE_DIGITS_RE = re.compile(r"^\d{3,9}$")

SCRAPER_METADATA_CATALOG: dict[str, dict[str, Any]] = {
    "ymgal": {
        "name": "YMGal 月幕 Galgame",
        "short_name": "YMGal",
        "description": "中文 Galgame 档案库，支持 GA 编号直查与 OAuth / 公开只读检索",
        "requires_key": False,
        "categories": ["galgame"],
        "doc_url": "https://www.ymgal.games/developer",
        "doc_hint": "默认使用公开只读接口，填写开发者凭证可提高配额。",
    },
    "kungal": {
        "name": "Kungal 鲲Gal",
        "short_name": "Kungal",
        "description": "中文视觉小说社区资料库，支持 kungal.com/galgame/{id} 直查与自定义镜像",
        "requires_key": False,
        "categories": ["galgame"],
        "doc_url": "https://www.kungal.com",
        "doc_hint": "默认使用 kungal.com，可配置自定义地址或访问 Token。",
    },
    "dlsite": {
        "name": "DLsite",
        "short_name": "DLsite",
        "description": "同人 / 独立视觉小说，支持 RJ / VJ / BJ 作品编号与链接直查",
        "requires_key": False,
        "categories": ["galgame"],
        "doc_url": "https://www.dlsite.com",
        "doc_hint": "免 Key，支持粘贴 RJ / VJ 编号或商品链接查询。",
    },
    "vndb": {
        "name": "VNDB",
        "short_name": "VNDB",
        "description": "视觉小说数据库（API v2），支持 v{id} 直查与 Steam / DLsite 关联",
        "requires_key": False,
        "categories": ["galgame"],
        "doc_url": "https://api.vndb.org/kana",
        "doc_hint": "免 Key，支持提取原名、别名、标签与 Steam / DLsite 外链。",
    },
    "bangumi": {
        "name": "Bangumi 番组计划",
        "short_name": "Bangumi",
        "description": "中文游戏条目、剧情简介、别名与评分（支持 bgm.tv/subject/{id} 直查）",
        "requires_key": False,
        "categories": ["galgame", "general"],
        "doc_url": "https://next.bgm.tv/demo/access-token",
        "doc_hint": "免 Key 可搜索，填写 Access Token 可提高限额并同步游玩状态。",
    },
    "steam": {
        "name": "Steam Store",
        "short_name": "Steam",
        "description": "中文商店元数据、官方 PV 预告片与 AppID / 商店链接直查",
        "requires_key": False,
        "categories": ["general"],
        "doc_url": "https://store.steampowered.com",
        "doc_hint": "免 Key，支持粘贴商店链接或数字 AppID 查询。",
    },
    "touchgal": {
        "name": "TouchGal",
        "short_name": "TouchGal",
        "description": "中文译名、简介与横版封面",
        "requires_key": True,
        "categories": ["galgame"],
        "doc_url": "https://developer.touchgal.com",
        "doc_hint": "填写 TouchGal 开发者 API Key（tgal_live_<id>-<secret>）后启用。",
    },
    "steamgriddb": {
        "name": "SteamGridDB",
        "short_name": "SteamGridDB",
        "description": "竖版封面、宽幅背景（Hero）与透明 Logo",
        "requires_key": True,
        "categories": [],
        "doc_url": "https://www.steamgriddb.com/profile/preferences/api",
        "doc_hint": "在 steamgriddb.com 的 Preferences / API 页面生成 Key，填写后可用于封面与背景查找。",
    },
    "igdb": {
        "name": "IGDB",
        "short_name": "IGDB",
        "description": "主机独占与非 Steam 单机元数据（Twitch OAuth 鉴权）",
        "requires_key": True,
        "categories": ["general"],
        "doc_url": "https://dev.twitch.tv/console/apps",
        "doc_hint": "在 Twitch 开发者控制台获取 Client ID 与 Secret，填写后启用。",
    },
}


def has_chinese(text: str | None) -> bool:
    return bool(_CJK_RE.search(text or ""))


def is_derivative_title(text: str | None) -> bool:
    """判断标题是否属于 OST / Artbook / 设定集 / Drama CD / 体验版 等衍生条目"""
    if not text:
        return False
    return any(p.search(text) for p in _DERIVATIVE_PATTERNS)


def query_requests_derivative(query: str | None) -> bool:
    """判断用户搜索词本身是否明确在搜衍生条目"""
    return is_derivative_title(query)


def _single_title_match_score(q_norm: str, cand_norm: str, *, is_alias: bool = False) -> float:
    if not q_norm or not cand_norm:
        return 0.0

    # 1. 精确命中（最高优先级）
    if cand_norm == q_norm:
        return 92.0 if is_alias else 95.0

    # 2. 前缀匹配（次高优先级）
    if cand_norm.startswith(q_norm):
        ratio = len(q_norm) / max(len(cand_norm), 1)
        base = 76.0 + 12.0 * ratio
        return base - (1.5 if is_alias else 0.0)

    if len(cand_norm) >= 3 and q_norm.startswith(cand_norm):
        ratio = len(cand_norm) / max(len(q_norm), 1)
        base = 70.0 + 10.0 * ratio
        return base - (1.5 if is_alias else 0.0)

    # 3. 子串包含
    if q_norm in cand_norm:
        ratio = len(q_norm) / max(len(cand_norm), 1)
        base = 56.0 + 14.0 * ratio
        return base - (1.5 if is_alias else 0.0)

    if len(cand_norm) >= 3 and cand_norm in q_norm:
        ratio = len(cand_norm) / max(len(q_norm), 1)
        base = 50.0 + 10.0 * ratio
        return base - (1.5 if is_alias else 0.0)

    # 4. 模糊编辑相似度兜底
    seq = SequenceMatcher(None, q_norm, cand_norm).ratio()
    return seq * (45.0 if is_alias else 48.0)


def score_search_result(
    query: str,
    item: ScraperSearchResult,
    *,
    category: str = "all",
) -> float:
    """
    统一归一化相关性打分算法（0 ~ 100）：
    - 忽略全角/半角、大小写、常见标点、日文助词及常见繁简差异；
    - 精确命中标题/原名/别名 > 前缀匹配 > 子串包含 > 模糊相似度；
    - 标题含 OST / Soundtrack / Artbook / 设定集 / Drama CD / 体验版 等衍生条目自动降权（除非用户明确搜索这些词）。
    """
    if item.direct_hit:
        return 100.0

    q_norm = normalize_search_text(query)
    if not q_norm:
        return 0.0

    best = 0.0
    for primary_t in (item.title, item.original_title):
        if primary_t:
            c_norm = normalize_search_text(primary_t)
            best = max(best, _single_title_match_score(q_norm, c_norm, is_alias=False))

    for alias in item.aliases or []:
        if alias:
            c_norm = normalize_search_text(alias)
            best = max(best, _single_title_match_score(q_norm, c_norm, is_alias=True))

    # 轻微完整度与分类来源优先级加权（不超过 +3.0，绝不破坏主匹配层级）
    bonus = 0.0
    if item.cover_url:
        bonus += 0.8
    if item.description:
        bonus += 0.7
    if item.developers:
        bonus += 0.4
    if item.release_date:
        bonus += 0.3

    preset = CATEGORY_PRESETS.get(category, CATEGORY_PRESETS["all"])
    norm_src = canonicalize_source_name(item.source)
    if norm_src in preset:
        rank_idx = preset.index(norm_src)
        bonus += max(0.1, 0.8 - rank_idx * 0.1)

    score = min(99.5, best + bonus)

    # 衍生条目自动降权（若用户未明确搜索 OST / 设定集 / 体验版 等词）
    if not query_requests_derivative(query):
        if is_derivative_title(item.title) or is_derivative_title(item.original_title):
            score = max(1.0, score - 40.0)

    return round(score, 2)


def rerank_results(
    query: str,
    items: list[ScraperSearchResult],
    *,
    category: str = "all",
    limit: int | None = None,
) -> list[ScraperSearchResult]:
    """对多源候选结果去重、计算归一化相关性得分并重排"""
    deduped: list[ScraperSearchResult] = []
    seen_keys: set[tuple[str, str]] = set()

    for it in items:
        norm_src = canonicalize_source_name(it.source)
        key = (norm_src, (it.source_id or it.title).strip().lower())
        if key in seen_keys:
            continue
        seen_keys.add(key)
        it.match_score = score_search_result(query, it, category=category)
        deduped.append(it)

    deduped.sort(
        key=lambda x: (
            1 if x.direct_hit else 0,
            x.match_score,
            1 if x.cover_url else 0,
            1 if x.description else 0,
        ),
        reverse=True,
    )

    if limit is not None and limit > 0:
        return deduped[:limit]
    return deduped


def _title_pair_similarity(a: str, b: str) -> tuple[float, bool]:
    na, nb = normalize_search_text(a), normalize_search_text(b)
    if not na or not nb:
        return 0.0, False
    if na == nb:
        return 1.0, True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) <= 2:
        return 0.0, False
    min_contain_len = 4 if shorter.isascii() else 3
    seq = SequenceMatcher(None, na, nb).ratio()
    if len(shorter) >= min_contain_len:
        if longer.startswith(shorter) or (
            shorter in longer and (len(shorter) / max(len(longer), 1)) >= 0.45
        ):
            return max(0.84, seq), False
    return seq, False


def _is_same_work(
    ref_titles: list[str],
    ref_year: int | None,
    candidate: ScraperSearchResult,
    *,
    min_similarity: float = 0.58,
) -> bool:
    cand_titles = [
        t.strip()
        for t in (candidate.title, candidate.original_title, *(candidate.aliases or []))
        if t and t.strip()
    ]
    best_sim = 0.0
    any_exact = False
    for rt in ref_titles:
        for ct in cand_titles:
            sim, exact = _title_pair_similarity(rt, ct)
            if exact:
                any_exact = True
            if sim > best_sim:
                best_sim = sim

    if best_sim < min_similarity:
        return False

    cand_year = extract_year(candidate.release_date)
    if ref_year is not None and cand_year is not None:
        if abs(ref_year - cand_year) > 2 and not any_exact:
            return False
    return True


class ScraperManager:
    """
    统一多源刮削器注册表与并发容错调度器：
    - 统一管理 Kungal / YMGal / DLsite / VNDB / Bangumi / Steam / SteamGridDB / IGDB（及兼容 TouchGal）
    - 支持链接/编号直查（100% 精准命中并置顶）
    - 使用 asyncio.gather(..., return_exceptions=True) + 每源独立超时（默认 8s）实现完全异常隔离
    - 场景预设 + 归一化相关性重排 + 跨源字段/封面补全
    """

    def __init__(
        self,
        *,
        proxy_url: str = "",
        allow_nsfw: bool = True,
        scraper_settings: dict[str, Any] | None = None,
        per_source_timeout: float = DEFAULT_PER_SOURCE_TIMEOUT,
        scrapers_override: dict[str, BaseScraper] | None = None,
    ) -> None:
        self.proxy_url = (proxy_url or "").strip()
        self.allow_nsfw = bool(allow_nsfw)
        self.per_source_timeout = float(per_source_timeout)
        self.settings = {**default_scraper_settings(), **(scraper_settings or {})}
        self.enabled_sources: dict[str, bool] = {
            **default_scraper_settings()["enabled_sources"],
            **(self.settings.get("enabled_sources") or {}),
        }

        if scrapers_override is not None:
            self.scrapers: dict[str, BaseScraper] = dict(scrapers_override)
        else:
            self.scrapers = self._build_default_registry()

    def _build_default_registry(self) -> dict[str, BaseScraper]:
        s = self.settings
        t = self.per_source_timeout
        return {
            "ymgal": YMGalScraper(
                proxy_url=self.proxy_url,
                client_id=str(s.get("ymgal_client_id") or ""),
                client_secret=str(s.get("ymgal_client_secret") or ""),
                allow_nsfw=self.allow_nsfw,
                timeout=t,
            ),
            "kungal": KungalScraper(
                proxy_url=self.proxy_url,
                api_key=str(s.get("kungal_token") or ""),
                base_url=str(s.get("kungal_base_url") or DEFAULT_KUNGAL_BASE_URL),
                allow_nsfw=self.allow_nsfw,
                timeout=t,
            ),
            "dlsite": DLsiteScraper(
                proxy_url=self.proxy_url,
                allow_nsfw=self.allow_nsfw,
                timeout=t,
            ),
            "vndb": VNDBScraper(
                proxy_url=self.proxy_url,
                allow_nsfw=self.allow_nsfw,
                timeout=t,
            ),
            "bangumi": BangumiScraper(
                proxy_url=self.proxy_url,
                api_key=str(s.get("bangumi_token") or ""),
                allow_nsfw=self.allow_nsfw,
                timeout=t,
            ),
            "steam": SteamScraper(
                proxy_url=self.proxy_url,
                allow_nsfw=self.allow_nsfw,
                timeout=t,
            ),
            "steamgriddb": SteamGridDBScraper(
                proxy_url=self.proxy_url,
                api_key=str(s.get("steamgriddb_api_key") or ""),
                allow_nsfw=self.allow_nsfw,
                timeout=t,
            ),
            "igdb": IGDBScraper(
                proxy_url=self.proxy_url,
                client_id=str(s.get("igdb_client_id") or ""),
                client_secret=str(s.get("igdb_client_secret") or ""),
                allow_nsfw=self.allow_nsfw,
                timeout=t,
            ),
            "touchgal": TouchGalScraper(
                proxy_url=self.proxy_url,
                api_key=str(s.get("touchgal_api_key") or s.get("touchgal_token") or ""),
                allow_nsfw=self.allow_nsfw,
                timeout=t,
            ),
        }

    def get_scraper(self, source: str) -> BaseScraper | None:
        canon = canonicalize_source_name(source)
        return self.scrapers.get(canon)

    def is_source_enabled(self, source_id: str) -> bool:
        canon = canonicalize_source_name(source_id)
        if canon not in self.scrapers:
            return False
        return bool(self.enabled_sources.get(canon, True))

    def is_source_available(self, source_id: str) -> bool:
        scraper = self.get_scraper(source_id)
        if not scraper:
            return False
        return self.is_source_enabled(source_id) and scraper.is_configured()

    def list_source_descriptors(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for sid in ALL_MANAGED_SCRAPER_IDS:
            meta = SCRAPER_METADATA_CATALOG[sid]
            scraper = self.scrapers.get(sid)
            enabled = bool(self.enabled_sources.get(sid, True))
            configured = scraper.is_configured() if scraper else is_source_configured(sid, self.settings)
            out.append(
                {
                    "id": sid,
                    "name": meta["name"],
                    "short_name": meta["short_name"],
                    "description": meta["description"],
                    "requires_key": sid in KEY_SCRAPER_IDS,
                    "is_free": sid in FREE_SCRAPER_IDS,
                    "enabled": enabled,
                    "configured": configured,
                    "available": enabled and configured,
                    "categories": list(meta["categories"]),
                    "doc_url": meta["doc_url"],
                    "doc_hint": meta["doc_hint"],
                }
            )
        return out

    def detect_direct_id(self, query: str) -> tuple[str, str] | None:
        """
        识别用户输入是否为链接或作品编号（Steam / VNDB / Bangumi / YMGal / Kungal / DLsite / IGDB / SGDB）。
        返回 (canonical_source_id, parsed_source_id) 或 None。
        """
        q = (query or "").strip()
        if not q:
            return None
        for sid in DIRECT_ID_CHECK_ORDER:
            scraper = self.scrapers.get(sid)
            if not scraper:
                continue
            if scraper.supports_direct_id(q):
                parsed = scraper.parse_direct_id(q)
                if parsed:
                    return sid, parsed
        return None

    def resolve_target_sources(
        self,
        *,
        category: str | None = None,
        sources: list[str] | None = None,
    ) -> list[str]:
        """根据指定来源或默认全部启用源，过滤出当前可用且已配置的刮削器 ID 列表"""
        if sources:
            targets: list[str] = []
            for raw in sources:
                canon = canonicalize_source_name(raw)
                scraper = self.scrapers.get(canon)
                # 显式单选 TouchGal 时允许尝试调用（未配置 Key 也可回退公开搜索或给出明确提示）
                if scraper and (scraper.is_configured() or canon == "touchgal") and canon not in targets:
                    targets.append(canon)
            return targets

        cat = (category or "all").strip().lower()
        preset = CATEGORY_PRESETS.get(cat, CATEGORY_PRESETS["all"])
        return [sid for sid in preset if self.is_source_available(sid)]

    async def get_detail(
        self,
        source: str,
        source_id: str,
    ) -> ScraperGameDetail | None:
        canon = canonicalize_source_name(source)
        scraper = self.get_scraper(canon)
        if not scraper or (not scraper.is_configured() and canon != "touchgal"):
            return None
        try:
            detail = await asyncio.wait_for(
                scraper.get_detail(source_id),
                timeout=self.per_source_timeout,
            )
            return detail
        except asyncio.TimeoutError:
            logger.warning("Detail timeout on %s (%s)", source, source_id)
            return None
        except Exception as exc:
            logger.warning("Detail error on %s (%s): %s", source, source_id, exc)
            return None

    async def search(
        self,
        query: str,
        *,
        category: str | None = None,
        sources: list[str] | None = None,
        limit: int = 15,
    ) -> dict[str, Any]:
        """
        执行统一检索：
        1. 优先识别链接/编号直查，命中后直接拉取精确详情并置顶；
        2. 默认（综合推荐 / 未指定单源）并发全部已启用数据源，单源独立超时与异常隔离；
        3. 统一去重、归一化相关性打分与衍生条目降权重排。
        """
        cat = (category or "all").strip().lower()
        if cat not in CATEGORY_PRESETS:
            cat = "all"

        q = (query or "").strip()
        if not q:
            return {
                "query": "",
                "category": cat,
                "sources": [],
                "direct_match": None,
                "items": [],
                "source_errors": {},
            }

        source_errors: dict[str, str] = {}
        direct_match_info: dict[str, str] | None = None

        # 1. 链接与编号直查（100% 精准命中）
        direct = self.detect_direct_id(q)
        if direct:
            direct_src, direct_id = direct
            direct_scraper = self.scrapers.get(direct_src)
            is_pure_numeric = bool(_PURE_DIGITS_RE.match(q))
            explicit_sources = [canonicalize_source_name(s) for s in (sources or []) if s]

            # 若用户明确只选了某个其他源，则仅在该源与直查源一致时触发直查
            allow_direct = (
                direct_scraper is not None
                and (direct_scraper.is_configured() or direct_src == "touchgal")
                and (not explicit_sources or direct_src in explicit_sources)
            )
            if allow_direct:
                try:
                    detail = await asyncio.wait_for(
                        direct_scraper.get_detail(direct_id),
                        timeout=self.per_source_timeout,
                    )
                except asyncio.TimeoutError:
                    detail = None
                    source_errors[direct_src] = f"超时 (>{self.per_source_timeout:.0f}s)"
                except Exception as exc:
                    detail = None
                    source_errors[direct_src] = str(exc)

                if detail is not None:
                    detail.direct_hit = True
                    detail.match_score = 100.0
                    direct_match_info = {"source": direct_src, "source_id": detail.source_id or direct_id}
                    return {
                        "query": q,
                        "category": cat,
                        "sources": [direct_src],
                        "direct_match": direct_match_info,
                        "items": [detail],
                        "source_errors": source_errors,
                    }

                # 若是明确 URL / 前缀编号（非纯数字标题），直查未找到时直接返回空并附带状态，不再误搜其他源
                if not is_pure_numeric:
                    direct_match_info = {"source": direct_src, "source_id": direct_id}
                    return {
                        "query": q,
                        "category": cat,
                        "sources": [direct_src],
                        "direct_match": direct_match_info,
                        "items": [],
                        "source_errors": source_errors,
                    }

        # 2. 并发调度目标数据源（单源独立超时 + 异常隔离）
        target_sources = self.resolve_target_sources(category=cat, sources=sources)
        if not target_sources:
            return {
                "query": q,
                "category": cat,
                "sources": [],
                "direct_match": direct_match_info,
                "items": [],
                "source_errors": source_errors,
            }

        per_source_limit = max(5, min(limit, 12)) if len(target_sources) > 1 else max(1, min(limit, 25))

        async def _run_source(src_id: str) -> tuple[str, list[ScraperSearchResult]]:
            scraper = self.scrapers[src_id]
            items = await asyncio.wait_for(
                scraper.search(q, limit=per_source_limit),
                timeout=self.per_source_timeout,
            )
            return src_id, items

        raw_outcomes = await asyncio.gather(
            *[_run_source(sid) for sid in target_sources],
            return_exceptions=True,
        )

        collected: list[ScraperSearchResult] = []
        for sid, outcome in zip(target_sources, raw_outcomes):
            if isinstance(outcome, asyncio.TimeoutError):
                logger.warning("Scraper %s timed out after %.1fs for %r", sid, self.per_source_timeout, q)
                source_errors[sid] = f"请求超时 (>{self.per_source_timeout:.0f}s)"
                continue
            if isinstance(outcome, Exception):
                logger.warning("Scraper %s failed for %r: %s", sid, q, outcome)
                source_errors[sid] = str(outcome)
                continue
            _src, batch = outcome
            if sid == "touchgal" and not batch and not self.scrapers["touchgal"].is_configured():
                source_errors["touchgal"] = "未配置 TouchGal API Key，建议前往设置页填写后重试"
            collected.extend(batch)

        # 3. 统一归一化相关性打分与衍生条目降权重排
        ranked = rerank_results(q, collected, category=cat, limit=limit)

        return {
            "query": q,
            "category": cat,
            "sources": target_sources,
            "direct_match": direct_match_info,
            "items": ranked,
            "source_errors": source_errors,
        }

    async def enrich(
        self,
        *,
        title: str,
        original_title: str = "",
        aliases: list[str] | None = None,
        release_date: str = "",
        source: str = "",
        source_id: str = "",
        external_ids: dict[str, str] | None = None,
        target_sources: list[str] | None = None,
        mode: str = "all",
    ) -> dict[str, Any]:
        """
        跨源字段与封面补全（Cross-Source Enrichment）：
        - 例如用 VNDB/DLsite 定位主条目后，一键并发拉取 YMGal/Kungal/Bangumi 的中文简介，
          或从 SteamGridDB 按游戏名 / steam_appid 拉取 600×900 高清竖版封面与宽屏 Hero 背景。
        """
        ref_titles = [
            t.strip()
            for t in (title, original_title, *(aliases or []))
            if t and t.strip()
        ]
        if not ref_titles:
            return {
                "descriptions": [],
                "covers": [],
                "backgrounds": [],
                "logos": [],
                "merged_external_ids": normalize_external_ids(external_ids),
                "sgdb_configured": self.is_source_available("steamgriddb"),
                "warnings": [],
            }

        ref_year = extract_year(release_date)
        norm_ext = normalize_external_ids(external_ids)
        primary_src = canonicalize_source_name(source)
        if primary_src and source_id and primary_src not in norm_ext:
            norm_ext[primary_src] = source_id

        # 默认补全候选源：优先中文资料丰富的 YMGal / Kungal / TouchGal / Bangumi，其次 VNDB / Steam / DLsite / IGDB
        default_meta_sources = ["ymgal", "kungal", "touchgal", "bangumi", "vndb", "steam", "dlsite", "igdb"]
        if target_sources:
            meta_sources = [
                canonicalize_source_name(s)
                for s in target_sources
                if canonicalize_source_name(s) != "steamgriddb"
                and self.is_source_available(s)
            ]
            include_sgdb = any(canonicalize_source_name(s) == "steamgriddb" for s in target_sources)
        else:
            meta_sources = [s for s in default_meta_sources if self.is_source_available(s)]
            include_sgdb = mode in ("all", "covers")

        search_term_primary = (original_title or title).strip()
        search_term_alt = title.strip() if title.strip() != search_term_primary else ""

        async def _fetch_meta_from_source(sid: str) -> ScraperGameDetail | None:
            scraper = self.scrapers[sid]
            known_id = norm_ext.get(sid)
            if known_id:
                det = await asyncio.wait_for(
                    scraper.get_detail(known_id),
                    timeout=self.per_source_timeout,
                )
                if det:
                    return det

            # 关键词检索并用同作品守卫筛选
            query_terms = [search_term_primary] + ([search_term_alt] if search_term_alt else [])
            if sid in ("ymgal", "kungal", "touchgal", "bangumi") and has_chinese(title):
                query_terms = [title.strip()] + ([original_title.strip()] if original_title.strip() else [])

            best_cand: ScraperSearchResult | None = None
            for qt in dict.fromkeys(t for t in query_terms if t):
                cands = await asyncio.wait_for(
                    scraper.search(qt, limit=5),
                    timeout=self.per_source_timeout,
                )
                for c in cands:
                    if not query_requests_derivative(qt) and is_derivative_title(c.title):
                        continue
                    if _is_same_work(ref_titles, ref_year, c):
                        best_cand = c
                        break
                if best_cand:
                    break

            if not best_cand:
                return None

            # 若候选缺少简介或完整详情，继续拉一次详情
            if best_cand.source_id and (not best_cand.description or sid in ("ymgal", "bangumi", "steam", "dlsite", "kungal")):
                det = await asyncio.wait_for(
                    scraper.get_detail(best_cand.source_id),
                    timeout=self.per_source_timeout,
                )
                if det and _is_same_work(ref_titles, ref_year, det):
                    return det
            return ScraperGameDetail(**best_cand.model_dump())

        async def _fetch_sgdb_visuals() -> dict[str, list[dict[str, Any]]]:
            sgdb = self.scrapers.get("steamgriddb")
            if not isinstance(sgdb, SteamGridDBScraper) or not self.is_source_available("steamgriddb"):
                return {"covers": [], "backgrounds": [], "logos": []}
            return await asyncio.wait_for(
                sgdb.fetch_visual_candidates(
                    query=search_term_primary or title,
                    steam_appid=norm_ext.get("steam", ""),
                    limit=8,
                ),
                timeout=self.per_source_timeout,
            )

        meta_tasks = [_fetch_meta_from_source(sid) for sid in meta_sources]
        sgdb_task = _fetch_sgdb_visuals() if include_sgdb else None

        if sgdb_task is not None:
            all_results = await asyncio.gather(*meta_tasks, sgdb_task, return_exceptions=True)
            meta_outcomes = all_results[:-1]
            sgdb_outcome = all_results[-1]
        else:
            meta_outcomes = await asyncio.gather(*meta_tasks, return_exceptions=True)
            sgdb_outcome = {"covers": [], "backgrounds": [], "logos": []}

        descriptions: list[dict[str, Any]] = []
        covers: list[dict[str, Any]] = []
        backgrounds: list[dict[str, Any]] = []
        logos: list[dict[str, Any]] = []
        seen_cover_urls: set[str] = set()
        seen_bg_urls: set[str] = set()
        seen_logo_urls: set[str] = set()
        merged_ext = dict(norm_ext)
        warnings: list[str] = []

        # 1. 优先置顶 SteamGridDB 高清 600×900 竖版封面与宽屏 Hero
        if isinstance(sgdb_outcome, dict):
            for c in sgdb_outcome.get("covers") or []:
                u = c.get("url") or ""
                if u and u not in seen_cover_urls:
                    seen_cover_urls.add(u)
                    covers.append(c)
            for b in sgdb_outcome.get("backgrounds") or []:
                u = b.get("url") or ""
                if u and u not in seen_bg_urls:
                    seen_bg_urls.add(u)
                    backgrounds.append(b)
            for lg in sgdb_outcome.get("logos") or []:
                u = lg.get("url") or ""
                if u and u not in seen_logo_urls:
                    seen_logo_urls.add(u)
                    logos.append(lg)
        elif isinstance(sgdb_outcome, Exception):
            logger.debug("SGDB enrich failed: %s", sgdb_outcome)

        if include_sgdb and not self.is_source_available("steamgriddb"):
            warnings.append("SteamGridDB 未配置")

        # 2. 汇集各元数据来源的简介与图片
        for sid, outcome in zip(meta_sources, meta_outcomes):
            if isinstance(outcome, Exception) or outcome is None:
                continue
            det = outcome
            src_label = SOURCE_DISPLAY_NAMES.get(sid, sid.upper())

            # 收敛外站 ID
            for k, v in normalize_external_ids(det.external_ids).items():
                if v and k not in merged_ext:
                    merged_ext[k] = v
            if det.source_id and sid not in merged_ext:
                merged_ext[sid] = det.source_id

            if mode in ("all", "description") and (
                det.description or det.tags or det.developers or det.release_date
            ):
                descriptions.append(
                    {
                        "source": sid,
                        "source_name": src_label,
                        "source_id": det.source_id,
                        "source_url": det.source_url,
                        "title": det.title,
                        "original_title": det.original_title,
                        "description": det.description,
                        "developers": det.developers,
                        "publishers": det.publishers,
                        "release_date": det.release_date,
                        "tags": det.tags,
                        "has_chinese": has_chinese(det.description),
                        "external_ids": normalize_external_ids(det.external_ids),
                    }
                )

            if mode in ("all", "covers"):
                if det.cover_url and det.cover_url not in seen_cover_urls:
                    seen_cover_urls.add(det.cover_url)
                    digest = hashlib.sha1(f"{sid}:cover:{det.cover_url}".encode()).hexdigest()[:12]
                    covers.append(
                        {
                            "id": f"{sid}-cover-{digest}",
                            "source": sid,
                            "source_name": src_label,
                            "url": det.cover_url,
                            "thumb_url": det.cover_url,
                            "title": det.title,
                            "width": None,
                            "height": None,
                            "kind": "cover",
                        }
                    )
                if det.background_url and det.background_url not in seen_bg_urls:
                    seen_bg_urls.add(det.background_url)
                    digest = hashlib.sha1(f"{sid}:bg:{det.background_url}".encode()).hexdigest()[:12]
                    backgrounds.append(
                        {
                            "id": f"{sid}-bg-{digest}",
                            "source": sid,
                            "source_name": src_label,
                            "url": det.background_url,
                            "thumb_url": det.background_url,
                            "title": det.title,
                            "width": None,
                            "height": None,
                            "kind": "background",
                        }
                    )
                if det.logo_url and det.logo_url not in seen_logo_urls:
                    seen_logo_urls.add(det.logo_url)
                    digest = hashlib.sha1(f"{sid}:logo:{det.logo_url}".encode()).hexdigest()[:12]
                    logos.append(
                        {
                            "id": f"{sid}-logo-{digest}",
                            "source": sid,
                            "source_name": src_label,
                            "url": det.logo_url,
                            "thumb_url": det.logo_url,
                            "title": det.title,
                            "width": None,
                            "height": None,
                            "kind": "logo",
                        }
                    )

        # 中文简介优先排序（YMGal / Kungal / TouchGal / Bangumi 优先）
        zh_priority = {
            "ymgal": 0,
            "kungal": 1,
            "touchgal": 2,
            "bangumi": 3,
            "steam": 4,
            "vndb": 5,
            "dlsite": 6,
            "igdb": 7,
        }
        descriptions.sort(
            key=lambda d: (
                0 if d["has_chinese"] and d["description"] else (1 if d["description"] else 2),
                zh_priority.get(d["source"], 99),
            )
        )

        return {
            "descriptions": descriptions,
            "covers": covers,
            "backgrounds": backgrounds,
            "logos": logos,
            "merged_external_ids": normalize_external_ids(merged_ext),
            "sgdb_configured": self.is_source_available("steamgriddb"),
            "warnings": warnings,
        }

    async def test_source(self, source: str, timeout: float = 6.0) -> dict[str, Any]:
        scraper = self.get_scraper(source)
        if not scraper:
            return {
                "ok": False,
                "source": source,
                "latency_ms": 0,
                "detail": f"未知的数据源: {source}",
            }
        effective_timeout = max(2.0, float(timeout))
        try:
            return await asyncio.wait_for(
                scraper.test_connection(timeout=effective_timeout),
                timeout=effective_timeout + 0.5,
            )
        except asyncio.TimeoutError:
            return {
                "ok": False,
                "source": scraper.source_id,
                "latency_ms": int(effective_timeout * 1000),
                "detail": f"连接超时 (>{effective_timeout:.0f}s)，请检查网络或代理设置",
            }
        except Exception as exc:
            return {
                "ok": False,
                "source": scraper.source_id,
                "latency_ms": 0,
                "detail": f"连接异常: {exc}",
            }
