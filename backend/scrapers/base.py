from abc import ABC, abstractmethod
from collections.abc import Iterable
import re
from typing import Any
import httpx
from pydantic import BaseModel, Field

_PURE_DIGITS_RE = re.compile(r"^\d+(?:年)?$")
_SPLIT_ENTITY_RE = re.compile(r"[,，/、;；]+")

CANONICAL_PLATFORMS: dict[str, str] = {
    "pc": "PC",
    "steam": "Steam",
    "ps4": "PS4",
    "ps5": "PS5",
    "switch": "Switch",
}
_SCRAPER_SOURCE_NAMES = {"aggregated", "multi", "vndb", "bgm", "bangumi", "tgal", "touchgal", "sgdb", "steamgriddb", "local"}


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
    6. 按原序大小写不敏感去重，保留前 10 个高纯净度标签。
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


class ScrapedGameItem(BaseModel):
    """多源刮削统一数据结构：所有平台抓到的数据最终都标准化为此格式"""

    # 来源平台标识：VNDB / BGM / STEAM / SGDB / TGAL / AGGREGATED
    source: str
    external_id: str = ""

    # 核心文本元数据
    title: str
    sub_title: str = ""
    developer: str = ""
    publisher: str = ""
    release_date: str = ""
    synopsis: str = ""
    tags: list[str] = Field(default_factory=list)
    is_nsfw: bool = False

    # 在线视觉资产与媒体链接（确认导入后再由后端异步下载到本地）
    cover_url: str = ""
    logo_url: str = ""
    hero_bg_url: str = ""
    pv_url: str = ""
    screenshots: list[str] = Field(default_factory=list)

    # 聚合导入时用于保留多个平台的外部 ID 映射，如 {"vndb": "v17", "bgm": "1195"}
    extra_ids: dict[str, str] = Field(default_factory=dict)
    bangumi_id: str = ""


class BaseScraper(ABC):
    """所有第三方平台刮削器的抽象基类"""

    source_name: str = "BASE"

    def __init__(
        self,
        proxy_url: str = "",
        api_key: str = "",
        allow_nsfw: bool = True,
    ) -> None:
        self.proxy_url = proxy_url.strip()
        self.api_key = api_key.strip()
        self.allow_nsfw = allow_nsfw

    def _build_client(
        self,
        headers: dict[str, str] | None = None,
        timeout: float = 15.0,
    ) -> httpx.AsyncClient:
        """
        构造统一配置的异步 HTTP 客户端：
        自动注入默认 User-Agent、超时控制、重定向跟随及代理设置
        """
        default_headers = {
            "User-Agent": "TsumugiGameLibrary/0.3 (https://github.com/tsumugi-local)",
            "Accept": "application/json",
        }
        if headers:
            default_headers.update(headers)

        return httpx.AsyncClient(
            headers=default_headers,
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            # 注意：httpx 0.28+ 使用单数 proxy 参数，空字符串时转为 None 表示直连
            proxy=self.proxy_url or None,
        )

    @abstractmethod
    async def search(self, keyword: str, limit: int = 8) -> list[ScrapedGameItem]:
        """根据关键词检索候选游戏列表"""
        pass

    @abstractmethod
    async def get_detail(self, external_id: str) -> ScrapedGameItem | None:
        """根据平台唯一 ID 拉取完整详情与视觉资产"""
        pass