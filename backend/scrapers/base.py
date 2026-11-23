from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
import re
import time
import unicodedata
from typing import Any

import httpx
from pydantic import BaseModel, Field

_PURE_DIGITS_RE = re.compile(r"^\d+(?:年)?$")
_SPLIT_ENTITY_RE = re.compile(r"[,，/、;；]+")
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_NORM_STRIP_RE = re.compile(
    r"[\s\-—–_~～·・•:：!！?？()（）\[\]【】「」『』《》'\"`.,，。、/\\*＊☆★♪♥+&]+"
)

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
        "萬": "万",
        "與": "与",
        "為": "为",
        "無": "无",
        "見": "见",
        "長": "长",
        "點": "点",
    }
)

CANONICAL_PLATFORMS: dict[str, str] = {
    "pc": "PC",
    "steam": "Steam",
    "ps4": "PS4",
    "ps5": "PS5",
    "switch": "Switch",
}

_SCRAPER_SOURCE_NAMES = {
    "aggregated",
    "multi",
    "vndb",
    "bgm",
    "bangumi",
    "tgal",
    "touchgal",
    "sgdb",
    "steamgriddb",
    "kungal",
    "ymgal",
    "dlsite",
    "igdb",
    "local",
}

CANONICAL_SOURCE_ALIASES: dict[str, str] = {
    "kungal": "kungal",
    "kun": "kungal",
    "ymgal": "ymgal",
    "ym": "ymgal",
    "dlsite": "dlsite",
    "dl": "dlsite",
    "vndb": "vndb",
    "bangumi": "bangumi",
    "bgm": "bangumi",
    "steam": "steam",
    "steamgriddb": "steamgriddb",
    "sgdb": "steamgriddb",
    "igdb": "igdb",
    "touchgal": "touchgal",
    "tgal": "touchgal",
}

SOURCE_DISPLAY_NAMES: dict[str, str] = {
    "ymgal": "YMGal",
    "kungal": "Kungal",
    "dlsite": "DLsite",
    "vndb": "VNDB",
    "bangumi": "Bangumi",
    "steam": "Steam",
    "steamgriddb": "SteamGridDB",
    "igdb": "IGDB",
    "touchgal": "TouchGal",
}

_EXTERNAL_ID_KEY_MAP: dict[str, str] = {
    "steam": "steam",
    "steam_appid": "steam",
    "vndb": "vndb",
    "vndb_id": "vndb",
    "bgm": "bangumi",
    "bangumi": "bangumi",
    "bangumi_id": "bangumi",
    "ymgal": "ymgal",
    "ymgal_id": "ymgal",
    "kungal": "kungal",
    "kungal_id": "kungal",
    "dlsite": "dlsite",
    "dlsite_id": "dlsite",
    "igdb": "igdb",
    "igdb_id": "igdb",
    "sgdb": "steamgriddb",
    "steamgriddb": "steamgriddb",
    "tgal": "touchgal",
    "touchgal": "touchgal",
}

# 旧版代码中使用的大写来源标识映射（兼容历史客户端与聚合器）
LEGACY_SOURCE_LABELS: dict[str, str] = {
    "bangumi": "BGM",
    "vndb": "VNDB",
    "steam": "STEAM",
    "steamgriddb": "SGDB",
    "touchgal": "TGAL",
    "kungal": "KUNGAL",
    "ymgal": "YMGAL",
    "dlsite": "DLSITE",
    "igdb": "IGDB",
}


def canonicalize_source_name(raw: str | None) -> str:
    key = str(raw or "").strip().lower()
    return CANONICAL_SOURCE_ALIASES.get(key, key)


def normalize_search_text(text: str | None) -> str:
    """统一归一化文本：全角转半角(NFKC)、繁简/日文助词映射、转小写、去除常见标点空白"""
    if not text:
        return ""
    nfkc = unicodedata.normalize("NFKC", str(text))
    mapped = nfkc.translate(_VARIANT_TRANSLATION)
    return _NORM_STRIP_RE.sub("", mapped.lower())


def extract_year(raw: str | None) -> int | None:
    if not raw:
        return None
    m = _YEAR_RE.search(str(raw))
    return int(m.group(1)) if m else None


def split_entity_names(raw: str | Iterable[str] | None) -> list[str]:
    """将开发商/发行商字符串或数组拆分为去重列表"""
    if not raw:
        return []
    items: list[str] = []
    if isinstance(raw, str):
        parts = _SPLIT_ENTITY_RE.split(raw)
    else:
        parts = []
        for entry in raw:
            if isinstance(entry, str):
                parts.extend(_SPLIT_ENTITY_RE.split(entry))
    seen: set[str] = set()
    for p in parts:
        cleaned = p.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key not in seen:
            seen.add(key)
            items.append(cleaned)
    return items


def normalize_external_ids(raw: dict[str, Any] | None) -> dict[str, str]:
    """将各来源外部 ID 统一收敛为标准键：steam / vndb / bangumi / ymgal / kungal / dlsite / igdb"""
    out: dict[str, str] = {}
    if not raw or not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        if v is None:
            continue
        val = str(v).strip()
        if not val:
            continue
        canonical_key = _EXTERNAL_ID_KEY_MAP.get(str(k).strip().lower(), str(k).strip().lower())
        if canonical_key == "vndb":
            if val.lower().startswith("v") and val[1:].isdigit():
                val = f"v{val[1:]}"
            elif val.isdigit():
                val = f"v{val}"
        elif canonical_key == "ymgal":
            if val.isdigit():
                val = f"GA{val}"
            elif val.upper().startswith("GA") and val[2:].isdigit():
                val = f"GA{val[2:]}"
        elif canonical_key == "dlsite":
            val = val.upper()
        if canonical_key not in out:
            out[canonical_key] = val
    return out


def normalize_platform_badge(
    raw_platform: str | None = None,
    external_ids: dict[str, Any] | None = None,
) -> str:
    """将来源标识规范化为发行/游玩平台角标（PC / Steam / PS4 / PS5 / Switch / 空）"""
    if raw_platform is None:
        raw = ""
    else:
        raw = str(raw_platform).strip()

    if raw == "":
        return ""

    low = raw.lower()
    if low in CANONICAL_PLATFORMS:
        return CANONICAL_PLATFORMS[low]

    if low in _SCRAPER_SOURCE_NAMES:
        if external_ids and str(external_ids.get("steam") or "").strip():
            return "Steam"
        return "PC"

    return raw


def clean_scraped_tags(
    tags: Iterable[str],
    title: str = "",
    sub_title: str = "",
    developer: str = "",
    publisher: str = "",
    max_tags: int = 10,
) -> list[str]:
    """
    清洗多源刮削得到的原始标签列表：
    1. 去除首尾空白并过滤空项；
    2. 过滤包含下划线 '_' 的英文 Slug 脏词（如 ef_-_the_first_tale.）；
    3. 过滤纯数字或纯年份（如 2006 / 2016）；
    4. 过滤与主标题、副标题、开发商、发行商重名（忽略大小写）的冗余标签；
    5. 过滤超过 24 字符的异常长句标签；
    6. 按原序大小写不敏感去重，保留前 max_tags 个高纯净度标签。
    """
    excluded: set[str] = set()
    for field_val in (title, sub_title, developer, publisher):
        cleaned_field = (field_val or "").strip()
        if not cleaned_field:
            continue
        excluded.add(cleaned_field.lower())
        for part in _SPLIT_ENTITY_RE.split(cleaned_field):
            p = part.strip()
            if p:
                excluded.add(p.lower())

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        t = str(raw or "").strip()
        if not t:
            continue
        if "_" in t:
            continue
        if len(t) > 24:
            continue
        if _PURE_DIGITS_RE.match(t):
            continue
        low = t.lower()
        if low in excluded or low in seen:
            continue
        seen.add(low)
        cleaned.append(t)
        if len(cleaned) >= max_tags:
            break

    return cleaned


class ScraperSearchResult(BaseModel):
    """统一搜索结果数据结构"""

    source: str
    source_id: str = ""
    source_url: str = ""
    title: str
    original_title: str = ""
    aliases: list[str] = Field(default_factory=list)
    developers: list[str] = Field(default_factory=list)
    publishers: list[str] = Field(default_factory=list)
    release_date: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    cover_url: str = ""
    background_url: str = ""
    external_ids: dict[str, str] = Field(default_factory=dict)
    match_score: float = 0.0

    # 扩展常用字段（与现有资产及前端功能无缝衔接）
    is_nsfw: bool = False
    rating: float | None = None
    logo_url: str = ""
    pv_url: str = ""
    screenshots: list[str] = Field(default_factory=list)
    direct_hit: bool = False
    already_in_library: bool = False
    existing_game_id: int | None = None

    def to_legacy_item(self) -> "ScrapedGameItem":
        norm_src = canonicalize_source_name(self.source)
        ext_ids = normalize_external_ids(self.external_ids)
        if self.source_id and norm_src and norm_src not in ext_ids:
            ext_ids[norm_src] = self.source_id
        # 兼容旧代码中读取 extra_ids["bgm"]
        extra = dict(ext_ids)
        if "bangumi" in extra and "bgm" not in extra:
            extra["bgm"] = extra["bangumi"]
        if "steamgriddb" in extra and "sgdb" not in extra:
            extra["sgdb"] = extra["steamgriddb"]
        if "touchgal" in extra and "tgal" not in extra:
            extra["tgal"] = extra["touchgal"]

        return ScrapedGameItem(
            source=LEGACY_SOURCE_LABELS.get(norm_src, self.source.upper()),
            external_id=self.source_id,
            title=self.title,
            sub_title=self.original_title,
            developer=", ".join(self.developers),
            publisher=", ".join(self.publishers),
            release_date=self.release_date,
            synopsis=self.description,
            tags=list(self.tags),
            is_nsfw=self.is_nsfw,
            cover_url=self.cover_url,
            logo_url=self.logo_url,
            hero_bg_url=self.background_url,
            pv_url=self.pv_url,
            screenshots=list(self.screenshots),
            extra_ids=extra,
            bangumi_id=str(ext_ids.get("bangumi") or ""),
        )

    def to_api_dict(self) -> dict[str, Any]:
        """序列化为同时包含新规范字段与旧版兼容字段的 API 字典"""
        data = self.model_dump()
        ext_ids = normalize_external_ids(self.external_ids)
        norm_src = canonicalize_source_name(self.source)
        if self.source_id and norm_src and norm_src not in ext_ids:
            ext_ids[norm_src] = self.source_id
        data["external_ids"] = ext_ids
        data["source"] = norm_src or self.source.lower()
        data["source_label"] = SOURCE_DISPLAY_NAMES.get(norm_src, self.source.upper())

        # 旧版兼容别名字段（确保 BangumiBindModal 等旧消费者零回归）
        extra = dict(ext_ids)
        if "bangumi" in extra and "bgm" not in extra:
            extra["bgm"] = extra["bangumi"]
        data["external_id"] = self.source_id
        data["sub_title"] = self.original_title
        data["developer"] = ", ".join(self.developers)
        data["publisher"] = ", ".join(self.publishers)
        data["synopsis"] = self.description
        data["hero_bg_url"] = self.background_url
        data["extra_ids"] = extra
        data["bangumi_id"] = str(ext_ids.get("bangumi") or "")
        return data


class ScraperGameDetail(ScraperSearchResult):
    """统一游戏详情数据结构（继承全部标准搜索字段并支持完整详情资产）"""

    pass


class ScrapedGameItem(BaseModel):
    """向后兼容的历史数据结构（供聚合器、批量扫描与老接口复用）"""

    source: str
    external_id: str = ""

    title: str
    sub_title: str = ""
    developer: str = ""
    publisher: str = ""
    release_date: str = ""
    synopsis: str = ""
    tags: list[str] = Field(default_factory=list)
    is_nsfw: bool = False

    cover_url: str = ""
    logo_url: str = ""
    hero_bg_url: str = ""
    pv_url: str = ""
    screenshots: list[str] = Field(default_factory=list)

    extra_ids: dict[str, str] = Field(default_factory=dict)
    bangumi_id: str = ""

    # 扩展标准字段（可选，便于平滑迁移）
    source_url: str = ""
    aliases: list[str] = Field(default_factory=list)
    developers: list[str] = Field(default_factory=list)
    publishers: list[str] = Field(default_factory=list)
    match_score: float = 0.0
    rating: float | None = None

    def to_game_detail(self) -> ScraperGameDetail:
        norm_src = canonicalize_source_name(self.source)
        ext_ids = normalize_external_ids(self.extra_ids)
        if self.bangumi_id and "bangumi" not in ext_ids:
            ext_ids["bangumi"] = self.bangumi_id
        if self.external_id and norm_src and norm_src not in ext_ids and norm_src != "aggregated":
            ext_ids[norm_src] = self.external_id
        return ScraperGameDetail(
            source=norm_src or self.source.lower(),
            source_id=self.external_id,
            source_url=self.source_url,
            title=self.title,
            original_title=self.sub_title,
            aliases=list(self.aliases),
            developers=self.developers or split_entity_names(self.developer),
            publishers=self.publishers or split_entity_names(self.publisher),
            release_date=self.release_date,
            description=self.synopsis,
            tags=list(self.tags),
            cover_url=self.cover_url,
            background_url=self.hero_bg_url,
            external_ids=ext_ids,
            match_score=self.match_score,
            is_nsfw=self.is_nsfw,
            rating=self.rating,
            logo_url=self.logo_url,
            pv_url=self.pv_url,
            screenshots=list(self.screenshots),
        )


class BaseScraper(ABC):
    """所有第三方元数据刮削器的统一抽象基类"""

    source_id: str = "base"
    source_name: str = "BASE"
    display_name: str = "Base"
    requires_api_key: bool = False
    categories: tuple[str, ...] = ("galgame", "general")
    default_timeout: float = 8.0

    def __init__(
        self,
        proxy_url: str = "",
        api_key: str = "",
        allow_nsfw: bool = True,
        timeout: float | None = None,
    ) -> None:
        self.proxy_url = (proxy_url or "").strip()
        self.api_key = (api_key or "").strip()
        self.allow_nsfw = bool(allow_nsfw)
        self.timeout = float(timeout) if timeout is not None else self.default_timeout

    def is_configured(self) -> bool:
        """是否具备运行所需的最低凭证配置（免 Key 源恒为 True）"""
        if not self.requires_api_key:
            return True
        return bool(self.api_key)

    def _build_client(
        self,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        cookies: dict[str, str] | None = None,
    ) -> httpx.AsyncClient:
        """构造统一配置的异步 HTTP 客户端，自动注入代理、超时与请求头"""
        default_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36 Tsumugi/0.9"
            ),
            "Accept": "application/json, text/plain, */*",
        }
        if headers:
            default_headers.update(headers)

        return httpx.AsyncClient(
            headers=default_headers,
            cookies=cookies,
            timeout=httpx.Timeout(timeout if timeout is not None else self.timeout),
            follow_redirects=True,
            proxy=self.proxy_url or None,
        )

    def supports_direct_id(self, query: str) -> bool:
        """判断输入是否为本数据源可直接定位的链接或作品编号"""
        return self.parse_direct_id(query) is not None

    @abstractmethod
    def parse_direct_id(self, query: str) -> str | None:
        """从用户输入（URL 或编号）提取本数据源的标准 source_id；不匹配则返回 None"""
        pass

    @abstractmethod
    async def search(self, query: str, limit: int = 8) -> list[ScraperSearchResult]:
        """根据关键词检索候选游戏列表"""
        pass

    @abstractmethod
    async def get_detail(self, source_id: str) -> ScraperGameDetail | None:
        """根据平台唯一 source_id 拉取完整详情与视觉资产"""
        pass

    async def test_connection(self, timeout: float = 6.0) -> dict[str, Any]:
        """默认连通性探测：尝试执行一次轻量检索并返回延迟与状态"""
        if not self.is_configured():
            return {
                "ok": False,
                "source": self.source_id,
                "latency_ms": 0,
                "detail": f"未配置 {self.display_name} API Key",
            }
        t0 = time.monotonic()
        try:
            items = await self.search("CLANNAD", limit=1)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return {
                "ok": True,
                "source": self.source_id,
                "latency_ms": elapsed_ms,
                "sample_count": len(items),
                "detail": f"连接正常 ({elapsed_ms}ms)",
            }
        except httpx.TimeoutException:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return {
                "ok": False,
                "source": self.source_id,
                "latency_ms": elapsed_ms,
                "detail": f"连接超时 (>{timeout:.0f}s)",
            }
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return {
                "ok": False,
                "source": self.source_id,
                "latency_ms": elapsed_ms,
                "detail": f"连接失败: {exc}",
            }
