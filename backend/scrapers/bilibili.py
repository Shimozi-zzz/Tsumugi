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


def _build_bili_headers() -> dict[str, str]:
    return {
        "User-Agent": BILIBILI_USER_AGENT,
        "Referer": BILIBILI_REFERER,
        "Origin": "https://www.bilibili.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


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
) -> list[dict[str, Any]]:
    """
    真实 Bilibili WBI 视频检索（自动管理 buvid3/buvid4 Cookie 与 30 分钟 WBI 签名缓存）。
    返回标准字典列表：[{ id, bvid, title, author, duration, thumbnail, url, source }]
    """
    cleaned = (keyword or "").strip()
    if not cleaned:
        return []

    effective_proxy = (proxy_url or "").strip() or None
    raw_entries: list[dict[str, Any]] = []

    try:
        raw_entries = await _do_wbi_search(cleaned, page_size, effective_proxy)
    except Exception as exc:
        if effective_proxy is not None:
            logger.warning(
                "Bilibili 经代理 (%s) 搜索 %r 失败: %s，尝试直连回退",
                effective_proxy,
                cleaned,
                exc,
            )
            try:
                raw_entries = await _do_wbi_search(cleaned, page_size, None)
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

    return results
