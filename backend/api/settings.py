from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.scraper_settings import (
    is_masked_placeholder,
    load_scraper_settings,
    mask_scraper_settings_for_client,
    mask_secret,
    sanitize_touchgal_token,
    save_scraper_settings,
)
from backend.db.database import get_db
from backend.db.models import AppStateSetting
from backend.schemas import SettingUpdate

router = APIRouter(prefix="/api/settings", tags=["Settings"])

# 数据源官方 Token / API Key 创建直达链接（只读元数据，供前端展示跳转）
SOURCE_TOKEN_LINKS: dict[str, str] = {
    "ymgal": "https://www.ymgal.games/developer",
    "kungal": "https://www.kungal.com",
    "bangumi": "https://next.bgm.tv/demo/access-token",
    "touchgal": "https://developer.touchgal.com",
    "steamgriddb": "https://www.steamgriddb.com/profile/preferences/api",
    "igdb": "https://dev.twitch.tv/console/apps",
}

# 系统默认配置字典：首次启动数据库为空时作为兜底返回值
DEFAULT_SETTINGS: dict[str, Any] = {
    "last_active_game_id": None,      # 上次查看/退出时的游戏 ID（实现启动即续玩）
    "shelf_view_mode": "spine",       # 3D 书架默认视角：spine(侧封出盘) / showcase(展柜)
    "proxy_url": "",                  # 网络代理地址，如 http://127.0.0.1:7890
    "le_exe_path": "",                # 全局 Locale Emulator (LEProc.exe) 路径
    "bangumi_token": "",              # Bangumi Access Token（同时与 settings.json 互通）
    "api_keys": {
        "steamgriddb": "",            # 用于获取透明艺术字 Logo 与高清 Hero 背景
        "touchgal": "",               # TouchGal 开发者 Token
        "bangumi": "",                # Bangumi 可选私人 Token
    },
    "allow_nsfw_scrape": True,        # 是否允许刮削成人向条目/图片
    "privacy_blur_mode": False,       # 一键隐私模糊遮罩开关
    "shelf_bg_mode": "linked",        # 回廊氛围背景：linked(联动氛围墙) / random(记忆漫游) / minimal(极简暗室)
    "bgm_autoplay": True,             # 回廊出盘时自动播放游戏原声
    "gallery_particles": True,        # 回廊空气感浮游光尘粒子开关
    "library_sort_by": "series_name", # 游戏库与回廊排序方式
    "library_sort_order": "asc",      # 排序方向：asc / desc
}

SHELF_BG_MODES = {"linked", "random", "minimal"}
LIBRARY_SORT_MODES = {"series_name", "recent_played", "release_date", "play_time", "created_at"}
LIBRARY_SORT_ORDERS = {"asc", "desc"}


def resolve_bangumi_token(cfg: dict[str, Any]) -> str:
    """兼容读取 settings.json、顶层 bangumi_token 或 api_keys.bangumi"""
    scraper_cfg = load_scraper_settings(db_cfg=cfg)
    from_json = str(scraper_cfg.get("bangumi_token") or "").strip()
    if from_json:
        return from_json
    top = str(cfg.get("bangumi_token") or "").strip()
    if top and not is_masked_placeholder(top):
        return top
    api_keys = cfg.get("api_keys")
    if isinstance(api_keys, dict):
        tok = str(api_keys.get("bangumi") or "").strip()
        if tok and not is_masked_placeholder(tok):
            return tok
    return ""


@router.get("")
async def get_all_settings(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """获取全部软件状态与全局配置（对所有敏感 Key 做脱敏掩码处理）"""
    result = await db.execute(select(AppStateSetting))
    stored = {row.key: row.value for row in result.scalars().all()}
    merged = {**DEFAULT_SETTINGS, **stored}

    scraper_cfg = load_scraper_settings(db_cfg=merged)
    masked_scraper = mask_scraper_settings_for_client(scraper_cfg)

    raw_api_keys = dict(DEFAULT_SETTINGS["api_keys"])
    if isinstance(merged.get("api_keys"), dict):
        raw_api_keys.update(merged["api_keys"])

    merged["bangumi_token"] = mask_secret(str(scraper_cfg.get("bangumi_token") or ""))
    merged["api_keys"] = {
        "steamgriddb": mask_secret(str(scraper_cfg.get("steamgriddb_api_key") or raw_api_keys.get("steamgriddb") or "")),
        "touchgal": mask_secret(str(scraper_cfg.get("touchgal_api_key") or raw_api_keys.get("touchgal") or "")),
        "bangumi": mask_secret(str(scraper_cfg.get("bangumi_token") or raw_api_keys.get("bangumi") or "")),
    }
    merged["scraper_settings"] = masked_scraper
    merged["source_links"] = dict(SOURCE_TOKEN_LINKS)
    return merged


@router.put("/{key}")
async def update_setting(
    key: str,
    payload: SettingUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新或写入单项配置（Upsert 模式；敏感字段保留脱敏占位符对应原值并同步 settings.json）"""
    if key not in DEFAULT_SETTINGS:
        raise HTTPException(status_code=400, detail=f"未知的配置项: {key}")
    if key == "shelf_bg_mode" and payload.value not in SHELF_BG_MODES:
        raise HTTPException(status_code=400, detail=f"非法的回廊背景模式: {payload.value}")
    if key == "library_sort_by" and payload.value not in LIBRARY_SORT_MODES:
        raise HTTPException(status_code=400, detail=f"非法的排序方式: {payload.value}")
    if key == "library_sort_order" and payload.value not in LIBRARY_SORT_ORDERS:
        raise HTTPException(status_code=400, detail=f"非法的排序方向: {payload.value}")

    value_to_store = payload.value

    if key == "bangumi_token":
        incoming = str(payload.value or "").strip()
        if is_masked_placeholder(incoming):
            return {"key": key, "value": incoming}
        value_to_store = incoming
        save_scraper_settings({"bangumi_token": incoming})
    elif key == "api_keys" and isinstance(payload.value, dict):
        existing_row = await db.get(AppStateSetting, "api_keys")
        current_keys = (
            dict(existing_row.value)
            if existing_row and isinstance(existing_row.value, dict)
            else dict(DEFAULT_SETTINGS["api_keys"])
        )
        scraper_updates: dict[str, Any] = {}
        for k, v in payload.value.items():
            s = str(v or "").strip()
            if is_masked_placeholder(s):
                continue
            current_keys[k] = s
            if k == "steamgriddb":
                scraper_updates["steamgriddb_api_key"] = s
            elif k == "touchgal":
                s = sanitize_touchgal_token(s)
                current_keys[k] = s
                scraper_updates["touchgal_api_key"] = s
            elif k == "bangumi":
                scraper_updates["bangumi_token"] = s
        value_to_store = current_keys
        if scraper_updates:
            save_scraper_settings(scraper_updates)

    setting = await db.get(AppStateSetting, key)
    if setting:
        setting.value = value_to_store
    else:
        db.add(AppStateSetting(key=key, value=value_to_store))

    if key == "bangumi_token":
        api_keys_row = await db.get(AppStateSetting, "api_keys")
        current_keys = (
            dict(api_keys_row.value)
            if api_keys_row and isinstance(api_keys_row.value, dict)
            else dict(DEFAULT_SETTINGS["api_keys"])
        )
        current_keys["bangumi"] = str(value_to_store or "")
        if api_keys_row:
            api_keys_row.value = current_keys
        else:
            db.add(AppStateSetting(key="api_keys", value=current_keys))
    elif key == "api_keys" and isinstance(value_to_store, dict) and "bangumi" in value_to_store:
        token_val = str(value_to_store.get("bangumi") or "").strip()
        bgm_row = await db.get(AppStateSetting, "bangumi_token")
        if bgm_row:
            bgm_row.value = token_val
        else:
            db.add(AppStateSetting(key="bangumi_token", value=token_val))

    await db.commit()

    # 敏感键响应脱敏
    if key == "bangumi_token":
        return {"key": key, "value": mask_secret(str(value_to_store or ""))}
    if key == "api_keys" and isinstance(value_to_store, dict):
        return {
            "key": key,
            "value": {k: mask_secret(str(v or "")) for k, v in value_to_store.items()},
        }
    return {"key": key, "value": value_to_store}
