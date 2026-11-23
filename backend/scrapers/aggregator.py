from __future__ import annotations

import asyncio
import logging
from difflib import SequenceMatcher
from typing import Any

from backend.core.scraper_settings import load_scraper_settings
from backend.scrapers.base import (
    BaseScraper,
    ScrapedGameItem,
    canonicalize_source_name,
    clean_scraped_tags,
    extract_year,
    normalize_external_ids,
    normalize_search_text,
)
from backend.scrapers.manager import ScraperManager, has_chinese
from backend.scrapers.steamgriddb import SteamGridDBScraper

logger = logging.getLogger("tsumugi.scrapers.aggregator")


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
    seq_ratio = SequenceMatcher(None, na, nb).ratio()

    if len(shorter) >= min_contain_len:
        if longer.startswith(shorter) or (
            shorter in longer and (len(shorter) / max(len(longer), 1)) >= 0.45
        ):
            return max(0.84, seq_ratio), False

    return seq_ratio, False


def _title_similarity(a: str, b: str) -> float:
    return _title_pair_similarity(a, b)[0]


def _item_titles(item: ScrapedGameItem) -> list[str]:
    return [
        t.strip()
        for t in (item.title, item.sub_title, *(item.aliases or []))
        if t and t.strip()
    ]


def _pair_title_metrics(
    primary: ScrapedGameItem,
    candidate: ScrapedGameItem,
) -> tuple[float, bool]:
    best_sim = 0.0
    any_exact = False
    for pt in _item_titles(primary):
        for ct in _item_titles(candidate):
            sim, exact = _title_pair_similarity(pt, ct)
            if exact:
                any_exact = True
            if sim > best_sim:
                best_sim = sim
    return best_sim, any_exact


def _is_same_work_candidate(
    primary: ScrapedGameItem,
    candidate: ScrapedGameItem,
    min_similarity: float = 0.58,
) -> bool:
    best_sim, any_exact = _pair_title_metrics(primary, candidate)
    if best_sim < min_similarity:
        return False

    y_primary = extract_year(primary.release_date)
    y_cand = extract_year(candidate.release_date)
    if y_primary is not None and y_cand is not None:
        if abs(y_primary - y_cand) > 2 and not any_exact:
            return False

    return True


def _pick_best_secondary_candidate(
    primary: ScrapedGameItem,
    candidates: list[ScrapedGameItem],
    max_scan: int = 5,
) -> ScrapedGameItem | None:
    y_primary = extract_year(primary.release_date)
    best_item: ScrapedGameItem | None = None
    best_score = -1.0

    for idx, cand in enumerate(candidates[:max_scan]):
        if not _is_same_work_candidate(primary, cand):
            continue
        sim, exact = _pair_title_metrics(primary, cand)
        score = sim + (0.25 if exact else 0.0) + max(0.0, (max_scan - idx) * 0.015)

        y_cand = extract_year(cand.release_date)
        if y_primary is not None and y_cand is not None:
            diff = abs(y_primary - y_cand)
            if diff == 0:
                score += 0.12
            elif diff == 1:
                score += 0.05

        if score > best_score:
            best_score = score
            best_item = cand

    return best_item


def _best_match_for_query(
    items: list[ScrapedGameItem],
    queries: list[str],
    min_score: float = 0.58,
) -> ScrapedGameItem | None:
    if not items:
        return None
    best_item: ScrapedGameItem | None = None
    best_score = 0.0
    for idx, item in enumerate(items[:5]):
        candidate_titles = _item_titles(item)
        local_max = 0.0
        for q in queries:
            if not q:
                continue
            for ct in candidate_titles:
                local_max = max(local_max, _title_similarity(q, ct))
        if local_max < min_score:
            continue
        weighted = local_max + max(0.0, (3 - idx) * 0.02)
        if weighted > best_score:
            best_score = weighted
            best_item = item
    return best_item


class MetadataAggregator:
    """
    多源异步聚合拼装引擎（基于统一 ScraperManager）：
    并发调度 YMGal / Kungal / DLsite / VNDB / Bangumi / Steam / IGDB / SteamGridDB，
    按最优权重组合元数据与高清视觉资产，并对所有副源执行同作品守卫校验。
    """

    def __init__(
        self,
        proxy_url: str = "",
        api_keys: dict[str, Any] | None = None,
        allow_nsfw: bool = True,
        scraper_settings: dict[str, Any] | None = None,
        per_source_timeout: float = 8.0,
    ) -> None:
        self.proxy_url = (proxy_url or "").strip()
        self.allow_nsfw = bool(allow_nsfw)
        self.api_keys = dict(api_keys or {})

        if scraper_settings is None:
            merged_settings = load_scraper_settings(db_cfg={"api_keys": self.api_keys})
        else:
            merged_settings = dict(scraper_settings)

        self.manager = ScraperManager(
            proxy_url=self.proxy_url,
            allow_nsfw=self.allow_nsfw,
            scraper_settings=merged_settings,
            per_source_timeout=per_source_timeout,
        )
        self.scrapers: dict[str, BaseScraper] = self.manager.scrapers

    def get_scraper(self, source: str) -> BaseScraper | None:
        return self.manager.get_scraper(source)

    async def search_source(
        self, source: str, keyword: str, limit: int = 8
    ) -> list[ScrapedGameItem]:
        scraper = self.get_scraper(source)
        if not scraper or not scraper.is_configured():
            return []
        try:
            items = await asyncio.wait_for(
                scraper.search(keyword, limit=limit),
                timeout=self.manager.per_source_timeout,
            )
            return [it.to_legacy_item() for it in items]
        except Exception as exc:
            logger.warning("search_source(%s) failed for %r: %s", source, keyword, exc)
            return []

    async def get_detail(self, source: str, external_id: str) -> ScrapedGameItem | None:
        detail = await self.manager.get_detail(source, external_id)
        return detail.to_legacy_item() if detail else None

    async def search_aggregated(
        self, keyword: str, limit: int = 8
    ) -> list[ScrapedGameItem]:
        res = await self.manager.search(keyword, category="all", limit=limit)
        return [it.to_legacy_item() for it in res["items"]]

    async def aggregate_detail(
        self,
        keyword: str,
        external_ids: dict[str, str] | None = None,
        preferred_source: str = "",
    ) -> dict[str, Any]:
        """根据关键词与已知外站 ID，并发拉取多源完整详情并按最优权重合并"""
        ids = normalize_external_ids(external_ids)
        resolved: dict[str, ScrapedGameItem] = {}

        core_candidates = ("ymgal", "kungal", "vndb", "bangumi", "dlsite", "steam", "igdb")
        core_sources = [s for s in core_candidates if self.manager.is_source_available(s)]
        if preferred_source:
            pref = canonicalize_source_name(preferred_source)
            if pref in self.scrapers and pref not in core_sources and self.scrapers[pref].is_configured():
                core_sources.insert(0, pref)

        async def _fetch_initial(
            src: str,
        ) -> tuple[str, ScrapedGameItem | None, list[ScrapedGameItem]]:
            ext_id = ids.get(src)
            if ext_id:
                detail = await self.get_detail(src, ext_id)
                if detail:
                    return src, detail, []
            candidates = await self.search_source(src, keyword, limit=5)
            return src, None, candidates

        init_results = await asyncio.gather(
            *[_fetch_initial(s) for s in core_sources],
            return_exceptions=True,
        )

        search_pools: dict[str, list[ScrapedGameItem]] = {}
        for res in init_results:
            if isinstance(res, Exception):
                logger.warning("Aggregate round-1 error: %s", res)
                continue
            src, pinned_detail, cands = res
            if pinned_detail:
                resolved[src] = pinned_detail
                for k, v in normalize_external_ids(pinned_detail.extra_ids).items():
                    if k not in ids and v:
                        ids[k] = v
            else:
                search_pools[src] = cands

        primary: ScrapedGameItem | None = None
        anchor_order = (
            [canonicalize_source_name(preferred_source)] if preferred_source else []
        ) + ["ymgal", "vndb", "bangumi", "kungal", "dlsite", "steam", "igdb"]
        for anchor_src in anchor_order:
            if anchor_src in resolved:
                primary = resolved[anchor_src]
                break

        if primary is None:
            best_anchor_src = ""
            best_anchor_cand: ScrapedGameItem | None = None
            best_anchor_score = 0.0
            for src in core_sources:
                cands = search_pools.get(src) or []
                match = _best_match_for_query(cands, [keyword], min_score=0.58)
                if not match:
                    continue
                sim = max((_title_similarity(keyword, t) for t in _item_titles(match)), default=0.0)
                if sim > best_anchor_score:
                    best_anchor_score = sim
                    best_anchor_src = src
                    best_anchor_cand = match

            if best_anchor_cand and best_anchor_src:
                if best_anchor_cand.external_id and best_anchor_src in (
                    "steam",
                    "bangumi",
                    "ymgal",
                    "kungal",
                    "dlsite",
                    "igdb",
                ):
                    full = await self.get_detail(best_anchor_src, best_anchor_cand.external_id)
                    primary = full or best_anchor_cand
                else:
                    primary = best_anchor_cand
                resolved[best_anchor_src] = primary
                search_pools.pop(best_anchor_src, None)
                for k, v in normalize_external_ids(primary.extra_ids).items():
                    if k not in ids and v:
                        ids[k] = v

        if primary is not None:
            async def _resolve_secondary(src: str) -> tuple[str, ScrapedGameItem | None]:
                if ids.get(src):
                    full_by_id = await self.get_detail(src, ids[src])
                    if full_by_id:
                        return src, full_by_id

                cands = list(search_pools.get(src) or [])
                best_cand = _pick_best_secondary_candidate(primary, cands, max_scan=5)
                if not best_cand:
                    alt_terms = [
                        t
                        for t in _item_titles(primary)
                        if normalize_search_text(t) != normalize_search_text(keyword)
                    ]
                    for term in alt_terms[:1]:
                        extra_cands = await self.search_source(src, term, limit=5)
                        best_cand = _pick_best_secondary_candidate(primary, extra_cands, max_scan=5)
                        if best_cand:
                            break

                if not best_cand:
                    return src, None

                if best_cand.external_id and src in (
                    "steam",
                    "bangumi",
                    "ymgal",
                    "kungal",
                    "dlsite",
                    "igdb",
                ):
                    full = await self.get_detail(src, best_cand.external_id)
                    final_item = full or best_cand
                else:
                    final_item = best_cand

                if not _is_same_work_candidate(primary, final_item):
                    return src, None
                return src, final_item

            remaining_sources = [s for s in core_sources if s not in resolved]
            sec_results = await asyncio.gather(
                *[_resolve_secondary(s) for s in remaining_sources],
                return_exceptions=True,
            )
            for res in sec_results:
                if isinstance(res, Exception):
                    logger.warning("Aggregate secondary error: %s", res)
                    continue
                src, item = res
                if item:
                    resolved[src] = item
                    for k, v in normalize_external_ids(item.extra_ids).items():
                        if k not in ids and v:
                            ids[k] = v

        # 补强 SteamGridDB 视觉资产（优先 Steam AppID 匹配）
        sgdb_scraper = self.scrapers.get("steamgriddb")
        if (
            isinstance(sgdb_scraper, SteamGridDBScraper)
            and self.manager.is_source_available("steamgriddb")
            and primary is not None
        ):
            sgdb_id = ids.get("steamgriddb", "")
            if not sgdb_id and ids.get("steam"):
                sgdb_id = await sgdb_scraper.find_id_by_steam_appid(ids["steam"])
            if not sgdb_id:
                search_terms: list[str] = []
                for src in ("steam", "vndb", "bangumi", "ymgal", "igdb"):
                    it = resolved.get(src)
                    if it:
                        if it.sub_title:
                            search_terms.append(it.sub_title)
                        if it.title:
                            search_terms.append(it.title)
                search_terms.append(keyword)
                for term in list(dict.fromkeys(search_terms))[:3]:
                    sgdb_candidates = await self.search_source("steamgriddb", term, limit=5)
                    best_sgdb = _pick_best_secondary_candidate(primary, sgdb_candidates, max_scan=5)
                    if best_sgdb:
                        sgdb_id = best_sgdb.external_id
                        break
            if sgdb_id:
                sgdb_detail = await self.get_detail("steamgriddb", sgdb_id)
                if sgdb_detail:
                    resolved["steamgriddb"] = sgdb_detail

        if not resolved:
            fallback = ScrapedGameItem(source="AGGREGATED", title=keyword)
            return {"item": fallback, "matched_sources": [], "sources_detail": {}}

        merged = self.merge_items(resolved)
        return {
            "item": merged,
            "matched_sources": list(resolved.keys()),
            "sources_detail": {k: v.model_dump() for k, v in resolved.items()},
        }

    @staticmethod
    def merge_items(sources: dict[str, ScrapedGameItem]) -> ScrapedGameItem:
        ymgal = sources.get("ymgal")
        kungal = sources.get("kungal")
        bgm = sources.get("bangumi") or sources.get("bgm")
        vndb = sources.get("vndb")
        dlsite = sources.get("dlsite")
        steam = sources.get("steam")
        igdb = sources.get("igdb")
        sgdb = sources.get("steamgriddb") or sources.get("sgdb")
        tgal = sources.get("touchgal") or sources.get("tgal")

        # 1. 中文标题优先：YMGal / Bangumi / Kungal / TouchGal > Steam > VNDB > DLsite > IGDB
        title_candidates = [
            it.title
            for it in (ymgal, bgm, kungal, tgal, steam, vndb, dlsite, igdb, sgdb)
            if it and it.title
        ]
        zh_titles = [t for t in title_candidates if has_chinese(t)]
        title = zh_titles[0] if zh_titles else (title_candidates[0] if title_candidates else "未命名游戏")

        # 2. 原文副标题
        sub_candidates = [
            cand
            for it in (vndb, ymgal, bgm, kungal, dlsite, steam, igdb, tgal)
            if it
            for cand in (it.sub_title, it.title)
            if cand and normalize_search_text(cand) != normalize_search_text(title)
        ]
        sub_title = sub_candidates[0] if sub_candidates else ""

        # 3. 中文剧情简介优先：YMGal / Kungal / Bangumi / TouchGal > Steam > DLsite > VNDB > IGDB
        synopsis_candidates = [
            it.synopsis
            for it in (ymgal, kungal, bgm, tgal, steam, dlsite, vndb, igdb)
            if it and it.synopsis
        ]
        zh_synopses = [s for s in synopsis_candidates if has_chinese(s)]
        synopsis = zh_synopses[0] if zh_synopses else (synopsis_candidates[0] if synopsis_candidates else "")

        # 4. 开发商、发行商与发售日
        developer = next(
            (
                it.developer
                for it in (vndb, ymgal, dlsite, bgm, kungal, steam, igdb, tgal)
                if it and it.developer
            ),
            "",
        )
        publisher = next(
            (
                it.publisher
                for it in (bgm, steam, igdb, ymgal, kungal, tgal, vndb)
                if it and it.publisher
            ),
            "",
        )
        release_date = next(
            (
                it.release_date
                for it in (vndb, ymgal, dlsite, bgm, kungal, steam, igdb, tgal)
                if it and it.release_date
            ),
            "",
        )

        # 5. 标签合并与清洗
        raw_merged_tags: list[str] = []
        for it in (ymgal, bgm, vndb, dlsite, kungal, steam, igdb, tgal):
            if it:
                raw_merged_tags.extend(it.tags)
        tags = clean_scraped_tags(
            raw_merged_tags,
            title=title,
            sub_title=sub_title,
            developer=developer,
            publisher=publisher,
            max_tags=10,
        )

        # 6. 视觉资产最优拼装
        logo_url = next((it.logo_url for it in (sgdb, steam) if it and it.logo_url), "")
        hero_bg_url = next(
            (
                it.hero_bg_url
                for it in (sgdb, steam, igdb, kungal, vndb, dlsite, tgal)
                if it and it.hero_bg_url
            ),
            "",
        )
        cover_url = next(
            (
                it.cover_url
                for it in (sgdb, ymgal, bgm, vndb, dlsite, kungal, steam, igdb, tgal)
                if it and it.cover_url
            ),
            "",
        )
        pv_url = next(
            (it.pv_url for it in (steam, bgm, vndb, tgal) if it and it.pv_url),
            "",
        )

        screenshots: list[str] = []
        seen_ss: set[str] = set()
        for it in (steam, igdb, vndb, dlsite, kungal, tgal):
            if not it:
                continue
            for ss in it.screenshots:
                if ss and ss not in seen_ss:
                    seen_ss.add(ss)
                    screenshots.append(ss)
                if len(screenshots) >= 12:
                    break

        is_nsfw = any(bool(it.is_nsfw) for it in sources.values())

        raw_ext: dict[str, Any] = {}
        for src_key, it in sources.items():
            if it.external_id:
                raw_ext[src_key] = it.external_id
            for k, v in (it.extra_ids or {}).items():
                if v and k not in raw_ext:
                    raw_ext[k] = v

        norm_ext = normalize_external_ids(raw_ext)
        extra_ids = dict(norm_ext)
        if "bangumi" in extra_ids and "bgm" not in extra_ids:
            extra_ids["bgm"] = extra_ids["bangumi"]

        if len(sources) == 1:
            only = next(iter(sources.values()))
            source_label = only.source
            ext_id = only.external_id
        else:
            source_label = "AGGREGATED"
            ext_id = (
                norm_ext.get("bangumi")
                or norm_ext.get("ymgal")
                or norm_ext.get("vndb")
                or norm_ext.get("steam")
                or norm_ext.get("dlsite")
                or norm_ext.get("kungal")
                or ""
            )

        return ScrapedGameItem(
            source=source_label,
            external_id=ext_id,
            title=title,
            sub_title=sub_title,
            developer=developer,
            publisher=publisher,
            release_date=release_date,
            synopsis=synopsis,
            tags=tags,
            is_nsfw=is_nsfw,
            cover_url=cover_url,
            logo_url=logo_url,
            hero_bg_url=hero_bg_url,
            pv_url=pv_url,
            screenshots=screenshots,
            extra_ids=extra_ids,
            bangumi_id=str(norm_ext.get("bangumi") or ""),
        )
