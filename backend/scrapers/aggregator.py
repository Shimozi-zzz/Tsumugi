import asyncio
import logging
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from backend.scrapers.bangumi import BangumiScraper
from backend.scrapers.base import BaseScraper, ScrapedGameItem, clean_scraped_tags
from backend.scrapers.steam import SteamScraper
from backend.scrapers.steamgriddb import SteamGridDBScraper
from backend.scrapers.touchgal import TouchGalScraper
from backend.scrapers.vndb import VNDBScraper

logger = logging.getLogger("tsumugi.scrapers.aggregator")

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_NORM_RE = re.compile(r"[\s\-—–_~～·・:：!！?？()（）\[\]【】「」『』《》'\"`.,，。、/\\]+")

# 常见日文假名助词与繁简/新旧字体变体归一化映射（如 天ノ少女 <-> 天之少女）
_VARIANT_TRANSLATION = str.maketrans(
    {
        "ノ": "之",
        "の": "之",
        "ヶ": "个",
        "ケ": "个",
        "華": "华",
        "國": "国",
        "學": "学",
        "櫻": "樱",
        "桜": "樱",
        "戀": "恋",
        "夢": "梦",
        "傳": "传",
        "伝": "传",
        "頌": "颂",
        "偽": "伪",
        "雙": "双",
        "蒼": "苍",
        "終": "终",
        "聖": "圣",
        "戰": "战",
        "戦": "战",
        "劍": "剑",
        "剣": "剑",
        "龍": "龙",
        "竜": "龙",
        "風": "风",
        "雲": "云",
        "紅": "红",
        "藍": "蓝",
        "銀": "银",
        "鐵": "铁",
        "門": "门",
        "開": "开",
        "間": "间",
        "時": "时",
        "東": "东",
        "書": "书",
        "畫": "画",
        "圖": "图",
        "図": "图",
        "館": "馆",
        "樂": "乐",
        "楽": "乐",
        "聲": "声",
        "声": "声",
        "響": "响",
        "愛": "爱",
        "殼": "壳",
        "殻": "壳",
        "虛": "虚",
        "實": "实",
        "実": "实",
        "錄": "录",
        "記": "记",
        "話": "话",
        "語": "语",
        "詩": "诗",
        "說": "说",
        "謎": "谜",
        "異": "异",
        "邊": "边",
        "遙": "遥",
        "遠": "远",
        "歸": "归",
        "還": "还",
        "離": "离",
        "飛": "飞",
        "繪": "绘",
        "絵": "绘",
        "駅": "站",
    }
)


def _normalize_title(text: str) -> str:
    if not text:
        return ""
    nfkc = unicodedata.normalize("NFKC", text)
    mapped = nfkc.translate(_VARIANT_TRANSLATION)
    return _NORM_RE.sub("", mapped.lower())


def _extract_year(raw: str | None) -> int | None:
    if not raw:
        return None
    m = _YEAR_RE.search(str(raw))
    return int(m.group(1)) if m else None


def _has_chinese(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _title_pair_similarity(a: str, b: str) -> tuple[float, bool]:
    """计算两个标题的归一化相似度，返回 (score, is_exact)"""
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return 0.0, False
    if na == nb:
        return 1.0, True

    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    # 1~2 字符极短标题（如 "少女"、"Fate" 前缀等）除非完全相等，绝不允许靠子串偶然撞字合并
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
    return [t.strip() for t in (item.title, item.sub_title) if t and t.strip()]


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
    """
    跨源同作品合并守卫：
    1. 归一化标题比对（兼容片假名助词与繁简变体）：完全一致或有效前缀/包含，否则相似度必须 >= 0.58；
    2. 发售年份交叉校验：双方均存在有效 4 位发售年份且相差 > 2 年（且非完全一致标题）时，直接拒绝合并。
    """
    best_sim, any_exact = _pair_title_metrics(primary, candidate)
    if best_sim < min_similarity:
        return False

    y_primary = _extract_year(primary.release_date)
    y_cand = _extract_year(candidate.release_date)
    if y_primary is not None and y_cand is not None:
        if abs(y_primary - y_cand) > 2 and not any_exact:
            return False

    return True


def _pick_best_secondary_candidate(
    primary: ScrapedGameItem,
    candidates: list[ScrapedGameItem],
    max_scan: int = 5,
) -> ScrapedGameItem | None:
    """遍历副源前 5 条候选，挑选通过同作品守卫且综合得分最高的条目；全部未通过则返回 None"""
    y_primary = _extract_year(primary.release_date)
    best_item: ScrapedGameItem | None = None
    best_score = -1.0

    for idx, cand in enumerate(candidates[:max_scan]):
        if not _is_same_work_candidate(primary, cand):
            continue
        sim, exact = _pair_title_metrics(primary, cand)
        score = sim + (0.25 if exact else 0.0) + max(0.0, (max_scan - idx) * 0.015)

        y_cand = _extract_year(cand.release_date)
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
    多源异步聚合拼装引擎：
    并发调度 Bangumi / VNDB / Steam / SteamGridDB / TouchGal，按最优权重组合：
    - 透明 Logo & 宽幅 Hero：SteamGridDB > Steam > TouchGal > VNDB
    - 中文标题与剧情简介：Bangumi / TouchGal > Steam > VNDB
    - 开发商与防剧透标签：VNDB > Bangumi > Steam > TouchGal
    - 官方宣传片 PV：Steam (.m3u8 / .mp4)
    """

    def __init__(
        self,
        proxy_url: str = "",
        api_keys: dict[str, str] | None = None,
        allow_nsfw: bool = True,
    ) -> None:
        keys = api_keys or {}
        self.proxy_url = proxy_url
        self.allow_nsfw = allow_nsfw
        self.api_keys = keys

        self.scrapers: dict[str, BaseScraper] = {
            "bgm": BangumiScraper(
                proxy_url=proxy_url,
                api_key=str(keys.get("bangumi") or ""),
                allow_nsfw=allow_nsfw,
            ),
            "vndb": VNDBScraper(
                proxy_url=proxy_url,
                allow_nsfw=allow_nsfw,
            ),
            "steam": SteamScraper(
                proxy_url=proxy_url,
                allow_nsfw=allow_nsfw,
            ),
            "sgdb": SteamGridDBScraper(
                proxy_url=proxy_url,
                api_key=str(keys.get("steamgriddb") or ""),
                allow_nsfw=allow_nsfw,
            ),
            "tgal": TouchGalScraper(
                proxy_url=proxy_url,
                api_key=str(keys.get("touchgal") or ""),
                allow_nsfw=allow_nsfw,
            ),
        }

    def get_scraper(self, source: str) -> BaseScraper | None:
        key = source.strip().lower()
        alias_map = {
            "bangumi": "bgm",
            "bgm": "bgm",
            "vndb": "vndb",
            "steam": "steam",
            "steamgriddb": "sgdb",
            "sgdb": "sgdb",
            "touchgal": "tgal",
            "tgal": "tgal",
        }
        canonical = alias_map.get(key)
        return self.scrapers.get(canonical) if canonical else None

    async def search_source(
        self, source: str, keyword: str, limit: int = 8
    ) -> list[ScrapedGameItem]:
        scraper = self.get_scraper(source)
        if not scraper:
            return []
        return await scraper.search(keyword, limit=limit)

    async def get_detail(self, source: str, external_id: str) -> ScrapedGameItem | None:
        scraper = self.get_scraper(source)
        if not scraper:
            return None
        return await scraper.get_detail(external_id)

    async def search_aggregated(
        self, keyword: str, limit: int = 8
    ) -> list[ScrapedGameItem]:
        """
        并发搜索全部可用源，将同款游戏的不同平台结果智能聚类并给出推荐聚合候选列表。
        """
        sources_order = ["bgm", "vndb", "steam", "tgal", "sgdb"]
        tasks = [self.scrapers[s].search(keyword, limit=limit) for s in sources_order]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        per_source: dict[str, list[ScrapedGameItem]] = {}
        for src, res in zip(sources_order, raw_results):
            if isinstance(res, Exception):
                logger.warning("Aggregated search error on %s: %s", src, res)
                per_source[src] = []
            else:
                per_source[src] = res

        # 收集主候选池：优先从 Bangumi / VNDB / Steam / TouchGal 中建立聚类
        clusters: list[dict[str, ScrapedGameItem]] = []
        primary_sources = ["bgm", "vndb", "steam", "tgal"]

        for src in primary_sources:
            for item in per_source.get(src, []):
                placed = False
                for cluster in clusters:
                    if src in cluster:
                        continue
                    rep = next(iter(cluster.values()))
                    if not _is_same_work_candidate(rep, item, min_similarity=0.68):
                        continue
                    cluster[src] = item
                    placed = True
                    break
                if not placed:
                    clusters.append({src: item})

        # 尝试为每个聚类匹配 SteamGridDB 结果
        sgdb_items = per_source.get("sgdb", [])
        if sgdb_items:
            for cluster in clusters:
                rep = next(iter(cluster.values()))
                sgdb_match = _pick_best_secondary_candidate(rep, sgdb_items, max_scan=5)
                if sgdb_match:
                    cluster["sgdb"] = sgdb_match

        # 按多源命中数量 + 与关键词匹配度综合排序
        def _cluster_score(cluster: dict[str, ScrapedGameItem]) -> tuple[int, float]:
            best_sim = 0.0
            for it in cluster.values():
                best_sim = max(
                    best_sim,
                    _title_similarity(keyword, it.title),
                    _title_similarity(keyword, it.sub_title),
                )
            return (len(cluster), best_sim)

        clusters.sort(key=_cluster_score, reverse=True)

        merged_candidates: list[ScrapedGameItem] = []
        for cluster in clusters[:limit]:
            merged_candidates.append(self.merge_items(cluster))

        return merged_candidates

    async def aggregate_detail(
        self,
        keyword: str,
        external_ids: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        根据关键词与已知外站 ID，并发拉取多源完整详情（含 Steam PV 与 SteamGridDB 透明 Logo / Hero）
        并对所有副源候选执行严格的同作品守卫校验（标题归一化 + 发售年份交叉校验），杜绝跨作品串台。
        """
        ids = {k.lower(): str(v).strip() for k, v in (external_ids or {}).items() if v}
        resolved: dict[str, ScrapedGameItem] = {}
        core_sources = ("vndb", "bgm", "steam", "tgal")

        # 1. 优先拉取已明确指定外站 ID 的锚点源；同时对未指定 ID 的源并发执行前 5 条候选检索
        async def _fetch_initial(
            src: str,
        ) -> tuple[str, ScrapedGameItem | None, list[ScrapedGameItem]]:
            scraper = self.scrapers[src]
            ext_id = ids.get(src)
            if ext_id:
                detail = await scraper.get_detail(ext_id)
                if detail:
                    return src, detail, []
            candidates = await scraper.search(keyword, limit=5)
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
                for k, v in pinned_detail.extra_ids.items():
                    if k not in ids and v:
                        ids[k] = v
            else:
                search_pools[src] = cands

        # 2. 确定主源锚点（Primary Anchor）：优先使用已钉选源；否则从各源前 5 条中挑选与关键词最贴合的唯一锚点
        primary: ScrapedGameItem | None = None
        for anchor_src in ("vndb", "bgm", "steam", "tgal"):
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
                if best_anchor_src in ("steam", "bgm") and best_anchor_cand.external_id:
                    full = await self.scrapers[best_anchor_src].get_detail(best_anchor_cand.external_id)
                    primary = full or best_anchor_cand
                else:
                    primary = best_anchor_cand
                resolved[best_anchor_src] = primary
                search_pools.pop(best_anchor_src, None)
                for k, v in primary.extra_ids.items():
                    if k not in ids and v:
                        ids[k] = v

        # 3. 对所有其余副源执行严格同作品守卫校验：优先取高匹配候选，拉取完整详情后再次交叉校验年份与标题
        if primary is not None:
            async def _resolve_secondary(src: str) -> tuple[str, ScrapedGameItem | None]:
                scraper = self.scrapers[src]
                # 若主源提供了精确外站 ID（如 VNDB 关联了 Steam AppID），优先直接按 ID 抓详情
                if ids.get(src):
                    full_by_id = await scraper.get_detail(ids[src])
                    if full_by_id:
                        return src, full_by_id

                cands = list(search_pools.get(src) or [])
                # 若主源给出了更准确的日文原名/中文名且首轮候选未命中，可用原名补搜一次
                best_cand = _pick_best_secondary_candidate(primary, cands, max_scan=5)
                if not best_cand:
                    alt_terms = [t for t in _item_titles(primary) if _normalize_title(t) != _normalize_title(keyword)]
                    for term in alt_terms[:1]:
                        extra_cands = await scraper.search(term, limit=5)
                        best_cand = _pick_best_secondary_candidate(primary, extra_cands, max_scan=5)
                        if best_cand:
                            break

                if not best_cand:
                    return src, None

                if src in ("steam", "bgm") and best_cand.external_id:
                    full = await scraper.get_detail(best_cand.external_id)
                    final_item = full or best_cand
                else:
                    final_item = best_cand

                # 详情补齐发售日期与完整标题后再次执行同作品守卫，彻底拦截年份串台
                if not _is_same_work_candidate(primary, final_item):
                    logger.info(
                        "Rejected mismatched secondary %s candidate %r (%s) against primary %r (%s)",
                        src,
                        final_item.title,
                        final_item.release_date,
                        primary.title,
                        primary.release_date,
                    )
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
                    for k, v in item.extra_ids.items():
                        if k not in ids and v:
                            ids[k] = v

        # 第二轮：并发补强 SteamGridDB（优先使用 Steam AppID 精确匹配，其次用通过守卫的标题检索）
        sgdb_scraper = self.scrapers["sgdb"]
        if isinstance(sgdb_scraper, SteamGridDBScraper) and sgdb_scraper.api_key and primary is not None:
            sgdb_id = ids.get("sgdb", "")
            if not sgdb_id and ids.get("steam"):
                sgdb_id = await sgdb_scraper.find_id_by_steam_appid(ids["steam"])
            if not sgdb_id:
                search_terms: list[str] = []
                for src in ("steam", "vndb", "bgm"):
                    it = resolved.get(src)
                    if it:
                        if it.sub_title:
                            search_terms.append(it.sub_title)
                        if it.title:
                            search_terms.append(it.title)
                search_terms.append(keyword)
                for term in list(dict.fromkeys(search_terms))[:3]:
                    sgdb_candidates = await sgdb_scraper.search(term, limit=5)
                    best_sgdb = _pick_best_secondary_candidate(primary, sgdb_candidates, max_scan=5)
                    if best_sgdb:
                        sgdb_id = best_sgdb.external_id
                        break
            if sgdb_id:
                sgdb_detail = await sgdb_scraper.get_detail(sgdb_id)
                if sgdb_detail:
                    resolved["sgdb"] = sgdb_detail

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
        """按产品规范的最优权重将多源数据拼装为单个标准化 ScrapedGameItem"""
        bgm = sources.get("bgm")
        vndb = sources.get("vndb")
        steam = sources.get("steam")
        sgdb = sources.get("sgdb")
        tgal = sources.get("tgal")

        # 1. 中文标题优先：Bangumi / TouchGal > Steam > VNDB
        title_candidates = [
            it.title for it in (bgm, tgal, steam, vndb, sgdb) if it and it.title
        ]
        zh_titles = [t for t in title_candidates if _has_chinese(t)]
        title = zh_titles[0] if zh_titles else (title_candidates[0] if title_candidates else "未命名游戏")

        # 2. 原文副标题（日文/英文原名）
        sub_candidates = [
            cand
            for it in (vndb, bgm, tgal, steam)
            if it
            for cand in (it.sub_title, it.title)
            if cand and _normalize_title(cand) != _normalize_title(title)
        ]
        sub_title = sub_candidates[0] if sub_candidates else ""

        # 3. 中文剧情简介优先：Bangumi / TouchGal > Steam > VNDB
        synopsis_candidates = [
            it.synopsis for it in (bgm, tgal, steam, vndb) if it and it.synopsis
        ]
        zh_synopses = [s for s in synopsis_candidates if _has_chinese(s)]
        synopsis = zh_synopses[0] if zh_synopses else (synopsis_candidates[0] if synopsis_candidates else "")

        # 4. 开发商（VNDB 优先）与发行商（Bangumi / Steam 优先）
        developer = next(
            (it.developer for it in (vndb, bgm, steam, tgal) if it and it.developer), ""
        )
        publisher = next(
            (it.publisher for it in (bgm, steam, tgal, vndb) if it and it.publisher), ""
        )
        release_date = next(
            (it.release_date for it in (vndb, bgm, steam, tgal) if it and it.release_date), ""
        )

        # 5. 标签合并与统一去脏清洗（保留前 10 个高纯净度标签）
        raw_merged_tags: list[str] = []
        for it in (bgm, vndb, steam, tgal):
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

        # 6. 视觉资产最优拼装：
        #    - 透明 Logo：SteamGridDB > Steam
        #    - 宽幅 Hero：SteamGridDB > Steam > TouchGal > VNDB
        #    - 竖版封面：VNDB / Bangumi / SteamGridDB / Steam / TouchGal
        #    - 官方 PV：Steam
        logo_url = next(
            (it.logo_url for it in (sgdb, steam) if it and it.logo_url), ""
        )
        hero_bg_url = next(
            (it.hero_bg_url for it in (sgdb, steam, tgal, vndb) if it and it.hero_bg_url), ""
        )
        cover_url = next(
            (it.cover_url for it in (sgdb, bgm, vndb, steam, tgal) if it and it.cover_url), ""
        )
        pv_url = next(
            (it.pv_url for it in (steam, bgm, vndb, tgal) if it and it.pv_url), ""
        )

        # 合并截图列表（去重）
        screenshots: list[str] = []
        seen_ss: set[str] = set()
        for it in (steam, vndb, tgal):
            if not it:
                continue
            for ss in it.screenshots:
                if ss and ss not in seen_ss:
                    seen_ss.add(ss)
                    screenshots.append(ss)
                if len(screenshots) >= 12:
                    break

        is_nsfw = any(bool(it.is_nsfw) for it in sources.values())

        # 合并外部 ID 映射
        extra_ids: dict[str, str] = {}
        for src_key, it in sources.items():
            if it.external_id:
                extra_ids[src_key] = it.external_id
            for k, v in it.extra_ids.items():
                if v and k not in extra_ids:
                    extra_ids[k] = v

        # 来源平台标记：单源保留原平台，多源优先主平台或 AGGREGATED
        if len(sources) == 1:
            only = next(iter(sources.values()))
            source_label = only.source
            ext_id = only.external_id
        else:
            source_label = "AGGREGATED"
            ext_id = extra_ids.get("bgm") or extra_ids.get("vndb") or extra_ids.get("steam") or ""

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
            bangumi_id=str(extra_ids.get("bgm") or extra_ids.get("bangumi") or ""),
        )
