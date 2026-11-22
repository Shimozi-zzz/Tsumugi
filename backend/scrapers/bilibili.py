import asyncio
import hashlib
import html
import logging
import re
import time
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger("tsumugi.scrapers.bilibili")

BILIBILI_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
BILIBILI_REFERER = "https://www.bilibili.com/"
BILIBILI_SEARCH_REFERER = "https://search.bilibili.com/"
BILIBILI_SPI_URL = "https://api.bilibili.com/x/frontend/finger/spi"
BILIBILI_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
BILIBILI_WBI_SEARCH_URL = "https://api.bilibili.com/x/web-interface/wbi/search/type"

# Bilibili 官方 WBI mixin_key 重排表
MIXIN_KEY_ENC_TAB: tuple[int, ...] = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
)

WBI_CACHE_TTL_SEC = 1800.0  # 30 分钟内存缓存
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WBI_FILTER_RE = re.compile(r"[!'()*]")

_cache_lock = asyncio.Lock()
_wbi_cache: dict[str, Any] = {
    "mixin_key": "",
    "buvid3": "",
    "buvid4": "",
    "expires_at": 0.0,
}


def _clean_html_title(raw: Any) -> str:
    text = str(raw or "")
    if not text:
        return ""
    stripped = _HTML_TAG_RE.sub("", text)
    return html.unescape(stripped).strip()


def parse_bilibili_duration(raw: Any) -> int:
    """将 B 站返回的 'MM:SS' 或 'HH:MM:SS' 时长字符串转换为秒数"""
    if isinstance(raw, (int, float)):
        return max(0, int(round(raw)))
    text = str(raw or "").strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    parts = text.split(":")
    try:
        nums = [int(p.strip()) for p in parts]
    except ValueError:
        return 0
    if len(nums) == 2:
        return max(0, nums[0] * 60 + nums[1])
    if len(nums) == 3:
        return max(0, nums[0] * 3600 + nums[1] * 60 + nums[2])
    return 0


def _normalize_thumb(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if s.startswith("//"):
        return f"https:{s}"
    if s.startswith("http://"):
        return f"https://{s[7:]}"
    return s


def _compute_mixin_key(img_url: str, sub_url: str) -> str:
    img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
    sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
    raw = img_key + sub_key
    if not raw:
        return ""
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB if i < len(raw))[:32]


def sign_wbi_params(params: dict[str, Any], mixin_key: str) -> dict[str, str]:
    """按 Bilibili WBI 规范对请求参数计算 wts 与 w_rid 签名"""
    wts = str(int(time.time()))
    signed: dict[str, str] = {}
    for k, v in params.items():
        clean_v = _WBI_FILTER_RE.sub("", str(v))
        signed[str(k)] = clean_v
    signed["wts"] = wts

    sorted_items = sorted(signed.items(), key=lambda kv: kv[0])
    query_str = "&".join(
        f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted_items
    )
    w_rid = hashlib.md5(f"{query_str}{mixin_key}".encode("utf-8")).hexdigest()
    signed["w_rid"] = w_rid
    return signed


def _build_bili_headers(referer: str = BILIBILI_SEARCH_REFERER) -> dict[str, str]:
    return {
        "User-Agent": BILIBILI_USER_AGENT,
        "Referer": referer,
        "Origin": "https://search.bilibili.com" if "search.bilibili.com" in referer else "https://www.bilibili.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


_TITLE_PUNCT_RE = re.compile(r"[\s\-_~～·•:：,，.。!！?？'\"`「」『』【】()（）\[\]《》/\\]+")
_SEGMENT_SPLIT_RE = re.compile(r"[\s\-_~～·•:：,，!！?？「」『』【】()（）\[\]《》/\\]+")
_QUERY_SUFFIX_RE = re.compile(
    r"\b(pv|op|ed|ost|bgm|mv|cm|trailer|opening|official)\b|(宣传片|预告片|预告|主题曲|主题歌|片头曲|官方)$",
    re.IGNORECASE,
)
_GENERIC_STOPWORDS = {
    "the", "and", "for", "with", "from", "of", "in", "to", "a", "an",
    "game", "edition", "complete", "remastered", "hd", "pc", "steam",
    "pv", "op", "ed", "ost", "bgm", "mv", "cm", "trailer", "official",
    "游戏", "宣传片", "预告", "主题曲", "片头曲", "官方", "完全版", "中文版", "重制版",
    "前篇", "后篇", "上篇", "下篇", "第一部", "第二部",
}
_PV_BOOST_WORDS = ("pv", "宣传片", "预告", "trailer", "官方", "official", "cm", "发售", "intro", "opening")
_PV_PENALTY_WORDS = ("实况", "流程", "攻略", "解说", "录播", "切片", "杂谈", "吐槽", "测评", "评测", "试玩")
_OP_BOOST_WORDS = ("op", "主题曲", "片头曲", "opening", "主题歌", "ost", "bgm", "原声", "完整版", "full", "mv")
_OP_PENALTY_WORDS = ("实况", "流程", "攻略", "解说", "录播", "教学", "钢琴", "piano", "翻唱", "cover", "鬼畜")


def _norm_bili_text(raw: str) -> str:
    return _TITLE_PUNCT_RE.sub("", (raw or "").strip().lower())


def extract_game_core_terms(game_titles: list[str]) -> tuple[list[str], list[str]]:
    """
    从作品中文名 / 原名 / 别名提取：
    - full_terms: 归一化后的完整标题
    - sub_terms: 去噪后的有效核心分段词（中文 >=2 字、英文 >=3 字母，剔除泛用词）
    """
    full_terms: list[str] = []
    sub_terms: list[str] = []

    for raw in game_titles:
        text = str(raw or "").strip()
        if not text:
            continue
        cleaned_raw = _QUERY_SUFFIX_RE.sub("", text).strip() or text
        norm_full = _norm_bili_text(cleaned_raw)
        if len(norm_full) >= 2 and norm_full not in _GENERIC_STOPWORDS and norm_full not in full_terms:
            full_terms.append(norm_full)

        for seg in _SEGMENT_SPLIT_RE.split(cleaned_raw):
            seg_norm = _norm_bili_text(seg)
            if not seg_norm or seg_norm in _GENERIC_STOPWORDS:
                continue
            is_ascii = seg_norm.isascii()
            min_len = 3 if is_ascii else 2
            if len(seg_norm) >= min_len and seg_norm not in sub_terms:
                sub_terms.append(seg_norm)

    return full_terms, sub_terms


def score_bilibili_relevance(
    video_title: str,
    game_titles: list[str],
    kind: str = "any",
) -> int:
    """
    评估 B 站视频标题与目标作品的相关性分数：
    - 0 表示完全不包含作品核心词（应被剔除，杜绝无关番剧/杂项视频污染）
    - >0 表示命中核心词，并按 PV / OP 关键词进行加权与杂项降权
    """
    full_terms, sub_terms = extract_game_core_terms(game_titles)
    if not full_terms and not sub_terms:
        return 1

    norm_video = _norm_bili_text(video_title)
    if not norm_video:
        return 0

    base_score = 0

    # 1. 完整作品名直接命中
    for ft in full_terms:
        if ft in norm_video:
            base_score = max(base_score, 120)
            break

    # 2. 核心分段词命中（例如“传颂之物”、“虚伪的假面”、“summer pockets”）
    if base_score == 0:
        matched_segs = [st for st in sub_terms if st in norm_video]
        if matched_segs:
            # 较长核心词（>=3字或英文>=4字母）单独命中即高可信；短 2 字词要求至少命中或占比高
            longest = max(len(m) for m in matched_segs)
            if longest >= 3 or len(matched_segs) >= 2 or any(len(ft) <= 3 for ft in full_terms):
                base_score = 70 + min(30, 15 * (len(matched_segs) - 1))

    # 3. CJK 2-gram 重叠兜底（兼容极少量异体字/假名如“天之少女”vs“天ノ少女”）
    if base_score == 0:
        for ft in full_terms:
            if len(ft) >= 4 and not ft.isascii():
                grams = {ft[i : i + 2] for i in range(len(ft) - 1)}
                hits = sum(1 for g in grams if g in norm_video)
                if grams and (hits / len(grams)) >= 0.5:
                    base_score = max(base_score, 45)

    # 未命中任何作品核心词：直接判定为无关结果
    if base_score <= 0:
        return 0

    lower_raw = (video_title or "").lower()
    bonus = 0
    if kind == "pv":
        if any(w in lower_raw for w in _PV_BOOST_WORDS):
            bonus += 28
        if any(w in lower_raw for w in _PV_PENALTY_WORDS):
            bonus -= 22
    elif kind == "op":
        if any(w in lower_raw for w in _OP_BOOST_WORDS):
            bonus += 28
        if any(w in lower_raw for w in _OP_PENALTY_WORDS):
            bonus -= 18

    return max(1, base_score + bonus)


def filter_and_rank_bilibili_results(
    items: list[dict[str, Any]],
    game_titles: list[str],
    kind: str = "any",
) -> list[dict[str, Any]]:
    """剔除标题不含作品核心词的 B 站无关视频，并按相关性 + PV/OP 权重重排"""
    clean_titles = [t.strip() for t in game_titles if t and t.strip()]
    if not clean_titles:
        return items

    scored: list[tuple[int, int, dict[str, Any]]] = []
    for idx, item in enumerate(items):
        score = score_bilibili_relevance(str(item.get("title") or ""), clean_titles, kind=kind)
        if score > 0:
            scored.append((score, -idx, item))

    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [entry[2] for entry in scored]


async def _ensure_wbi_session(
    client: httpx.AsyncClient,
    force_refresh: bool = False,
) -> tuple[str, dict[str, str]]:
    """
    获取并缓存 B 站 buvid3/buvid4 Cookie 与 WBI mixin_key（内存缓存 30 分钟）：
    1. /x/frontend/finger/spi -> b_3 / b_4
    2. /x/web-interface/nav -> wbi_img.img_url / sub_url -> mixin_key
    """
    now = time.monotonic()
    if (
        not force_refresh
        and _wbi_cache["mixin_key"]
        and _wbi_cache["buvid3"]
        and now < _wbi_cache["expires_at"]
    ):
        cookies = {"buvid3": _wbi_cache["buvid3"]}
        if _wbi_cache["buvid4"]:
            cookies["buvid4"] = _wbi_cache["buvid4"]
        return _wbi_cache["mixin_key"], cookies

    async with _cache_lock:
        now = time.monotonic()
        if (
            not force_refresh
            and _wbi_cache["mixin_key"]
            and _wbi_cache["buvid3"]
            and now < _wbi_cache["expires_at"]
        ):
            cookies = {"buvid3": _wbi_cache["buvid3"]}
            if _wbi_cache["buvid4"]:
                cookies["buvid4"] = _wbi_cache["buvid4"]
            return _wbi_cache["mixin_key"], cookies

        buvid3 = ""
        buvid4 = ""
        spi_resp = await client.get(BILIBILI_SPI_URL)
        spi_resp.raise_for_status()
        spi_json = spi_resp.json()
        spi_data = spi_json.get("data") if isinstance(spi_json, dict) else None
        if isinstance(spi_data, dict):
            buvid3 = str(spi_data.get("b_3") or "").strip()
            buvid4 = str(spi_data.get("b_4") or "").strip()

        cookies: dict[str, str] = {}
        if buvid3:
            cookies["buvid3"] = buvid3
            client.cookies.set("buvid3", buvid3, domain=".bilibili.com")
        if buvid4:
            cookies["buvid4"] = buvid4
            client.cookies.set("buvid4", buvid4, domain=".bilibili.com")

        nav_resp = await client.get(BILIBILI_NAV_URL, cookies=cookies)
        nav_resp.raise_for_status()
        nav_json = nav_resp.json()
        nav_data = nav_json.get("data") if isinstance(nav_json, dict) else None
        wbi_img = nav_data.get("wbi_img") if isinstance(nav_data, dict) else None
        if not isinstance(wbi_img, dict):
            raise RuntimeError(f"Bilibili nav 未返回 wbi_img: {nav_json}")

        img_url = str(wbi_img.get("img_url") or "")
        sub_url = str(wbi_img.get("sub_url") or "")
        mixin_key = _compute_mixin_key(img_url, sub_url)
        if not mixin_key:
            raise RuntimeError("无法从 Bilibili nav 计算有效 WBI mixin_key")

        _wbi_cache["mixin_key"] = mixin_key
        _wbi_cache["buvid3"] = buvid3
        _wbi_cache["buvid4"] = buvid4
        _wbi_cache["expires_at"] = time.monotonic() + WBI_CACHE_TTL_SEC
        return mixin_key, cookies


async def _do_wbi_search(
    keyword: str,
    page_size: int,
    proxy: str | None,
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(
        headers=_build_bili_headers(),
        timeout=httpx.Timeout(10.0),
        follow_redirects=True,
        proxy=proxy,
    ) as client:
        for attempt in range(2):
            mixin_key, cookies = await _ensure_wbi_session(
                client, force_refresh=(attempt > 0)
            )
            signed_params = sign_wbi_params(
                {
                    "search_type": "video",
                    "keyword": keyword,
                    "page": 1,
                    "page_size": page_size,
                },
                mixin_key,
            )
            resp = await client.get(
                BILIBILI_WBI_SEARCH_URL,
                params=signed_params,
                cookies=cookies,
            )
            if resp.status_code == 412 and attempt == 0:
                logger.warning("Bilibili WBI 搜索命中 HTTP 412，刷新 buvid/mixin_key 重试")
                continue
            resp.raise_for_status()
            payload = resp.json()
            code = payload.get("code") if isinstance(payload, dict) else None
            if code in (-352, -412, -403) and attempt == 0:
                logger.warning("Bilibili WBI 返回风控码 %s，刷新签名后重试", code)
                continue
            if code != 0:
                msg = payload.get("message") if isinstance(payload, dict) else str(payload)
                raise RuntimeError(f"Bilibili 搜索返回错误码 {code}: {msg}")

            data = payload.get("data") if isinstance(payload, dict) else None
            raw_list = data.get("result") if isinstance(data, dict) else None
            return raw_list if isinstance(raw_list, list) else []

    return []


async def search_bilibili_videos(
    keyword: str,
    *,
    page_size: int = 8,
    min_duration: int | None = None,
    max_duration: int | None = None,
    proxy_url: str = "",
    game_titles: list[str] | None = None,
    kind: str = "any",
) -> list[dict[str, Any]]:
    """
    真实 Bilibili WBI 视频检索（自动管理 buvid3/buvid4 Cookie 与 30 分钟 WBI 签名缓存）。
    传入 game_titles 时会执行严格的核心词相关性过滤与 PV/OP 加权重排，剔除无关视频。
    返回标准字典列表：[{ id, bvid, title, author, duration, thumbnail, url, source }]
    """
    cleaned = (keyword or "").strip()
    if not cleaned:
        return []

    fetch_size = max(page_size, 15) if game_titles else page_size
    effective_proxy = (proxy_url or "").strip() or None
    raw_entries: list[dict[str, Any]] = []

    try:
        raw_entries = await _do_wbi_search(cleaned, fetch_size, effective_proxy)
    except Exception as exc:
        if effective_proxy is not None:
            logger.warning(
                "Bilibili 经代理 (%s) 搜索 %r 失败: %s，尝试直连回退",
                effective_proxy,
                cleaned,
                exc,
            )
            try:
                raw_entries = await _do_wbi_search(cleaned, fetch_size, None)
            except Exception as direct_exc:
                logger.warning("Bilibili 直连搜索 %r 失败: %s", cleaned, direct_exc)
                return []
        else:
            logger.warning("Bilibili 搜索 %r 失败: %s", cleaned, exc)
            return []

    results: list[dict[str, Any]] = []
    seen_bvids: set[str] = set()

    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        bvid = str(entry.get("bvid") or "").strip()
        if not bvid or bvid in seen_bvids:
            continue

        title = _clean_html_title(entry.get("title"))
        if not title:
            continue

        duration = parse_bilibili_duration(entry.get("duration"))
        if min_duration is not None and duration > 0 and duration < min_duration:
            continue
        if max_duration is not None and duration > 0 and duration > max_duration:
            continue

        seen_bvids.add(bvid)
        video_url = f"https://www.bilibili.com/video/{bvid}"
        digest = hashlib.sha1(f"Bilibili:{bvid}".encode("utf-8")).hexdigest()[:12]
        results.append(
            {
                "id": f"bilibili-{digest}",
                "bvid": bvid,
                "title": title,
                "author": str(entry.get("author") or "Bilibili").strip(),
                "duration": duration,
                "thumbnail": _normalize_thumb(entry.get("pic")),
                "url": video_url,
                "source": "Bilibili",
            }
        )

    if game_titles:
        results = filter_and_rank_bilibili_results(results, game_titles, kind=kind)

    return results[:page_size]
