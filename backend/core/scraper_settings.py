from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
from typing import Any

from backend.core.config import DATA_DIR, SETTINGS_JSON_PATH

logger = logging.getLogger("tsumugi.core.scraper_settings")

_BEARER_PREFIX_RE = re.compile(r"^(?:bearer(?:\s+|$))+", re.IGNORECASE)


def sanitize_touchgal_token(raw: str | None) -> str:
    """
    清洗 TouchGal 开发者 API Token：
    - 去除首尾空白与换行符；
    - 若用户误粘贴了 'Bearer '（含大小写或重复）前缀，自动剥离，避免拼出重复的 'Bearer Bearer ...'。
    """
    if not raw:
        return ""
    cleaned = str(raw).strip()
    cleaned = _BEARER_PREFIX_RE.sub("", cleaned).strip()
    cleaned = re.sub(r"[\r\n]+", "", cleaned).strip()
    return cleaned

DEFAULT_KUNGAL_BASE_URL = "https://www.kungal.com"

FREE_SCRAPER_IDS: tuple[str, ...] = (
    "ymgal",
    "kungal",
    "dlsite",
    "vndb",
    "bangumi",
    "steam",
)

KEY_SCRAPER_IDS: tuple[str, ...] = (
    "touchgal",
    "steamgriddb",
    "igdb",
)

ALL_MANAGED_SCRAPER_IDS: tuple[str, ...] = FREE_SCRAPER_IDS + KEY_SCRAPER_IDS

SECRET_CREDENTIAL_FIELDS: frozenset[str] = frozenset(
    {
        "ymgal_client_secret",
        "kungal_token",
        "bangumi_token",
        "touchgal_api_key",
        "steamgriddb_api_key",
        "igdb_client_secret",
    }
)

ALL_CREDENTIAL_FIELDS: tuple[str, ...] = (
    "ymgal_client_id",
    "ymgal_client_secret",
    "kungal_base_url",
    "kungal_token",
    "bangumi_token",
    "touchgal_api_key",
    "steamgriddb_api_key",
    "igdb_client_id",
    "igdb_client_secret",
)

_ENV_FALLBACK_MAP: dict[str, str] = {
    "ymgal_client_id": "YMGAL_CLIENT_ID",
    "ymgal_client_secret": "YMGAL_CLIENT_SECRET",
    "kungal_base_url": "KUNGAL_BASE_URL",
    "kungal_token": "KUNGAL_TOKEN",
    "bangumi_token": "BANGUMI_TOKEN",
    "touchgal_api_key": "TOUCHGAL_API_KEY",
    "steamgriddb_api_key": "STEAMGRIDDB_API_KEY",
    "igdb_client_id": "IGDB_CLIENT_ID",
    "igdb_client_secret": "IGDB_CLIENT_SECRET",
}

_MASK_CHAR = "•"


def default_scraper_settings() -> dict[str, Any]:
    return {
        "enabled_sources": {
            "ymgal": True,
            "kungal": True,
            "dlsite": True,
            "vndb": True,
            "bangumi": True,
            "steam": True,
            "touchgal": True,
            "steamgriddb": True,
            "igdb": True,
        },
        "ymgal_client_id": "",
        "ymgal_client_secret": "",
        "kungal_base_url": DEFAULT_KUNGAL_BASE_URL,
        "kungal_token": "",
        "bangumi_token": "",
        "touchgal_api_key": "",
        "steamgriddb_api_key": "",
        "igdb_client_id": "",
        "igdb_client_secret": "",
    }


def mask_secret(value: str) -> str:
    """对敏感 API Key / Secret 做不可逆脱敏掩码，安全返回前端展示"""
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if len(cleaned) <= 4:
        return _MASK_CHAR * 6
    if len(cleaned) <= 8:
        return f"{cleaned[:1]}{_MASK_CHAR * 5}{cleaned[-1:]}"
    return f"{cleaned[:3]}{_MASK_CHAR * 6}{cleaned[-3:]}"


def is_masked_placeholder(value: str | None) -> bool:
    """判断前端提交值是否为脱敏占位符，避免保存时覆盖真实凭证"""
    if not value:
        return False
    return _MASK_CHAR in value or "****" in value


def _settings_file_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    return SETTINGS_JSON_PATH


def _read_raw_json(path: Path | None = None) -> dict[str, Any]:
    fp = _settings_file_path(path)
    if not fp.is_file():
        return {}
    try:
        raw = json.loads(fp.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception as exc:
        logger.warning("Failed reading %s: %s", fp, exc)
        return {}


def _write_raw_json(data: dict[str, Any], path: Path | None = None) -> None:
    fp = _settings_file_path(path)
    fp.parent.mkdir(parents=True, exist_ok=True)
    tmp = fp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, fp)


def load_scraper_settings(
    *,
    db_cfg: dict[str, Any] | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """
    读取本地 DATA_DIR/settings.json 中的多源刮削配置：
    优先级：settings.json > 数据库旧配置 (AppStateSetting) > 环境变量 > 默认值。
    """
    result = default_scraper_settings()
    raw = _read_raw_json(path)
    section = raw.get("scraper_sources") if isinstance(raw.get("scraper_sources"), dict) else {}

    # 1. 合并数据源开关
    enabled = dict(result["enabled_sources"])
    stored_enabled = section.get("enabled_sources") or section.get("enabled")
    if isinstance(stored_enabled, dict):
        for src_id in ALL_MANAGED_SCRAPER_IDS:
            if src_id in stored_enabled:
                enabled[src_id] = bool(stored_enabled[src_id])
    result["enabled_sources"] = enabled

    # 2. 合并凭证字段（支持旧 DB api_keys 与环境变量兜底）
    db_api_keys = (
        db_cfg.get("api_keys")
        if isinstance(db_cfg, dict) and isinstance(db_cfg.get("api_keys"), dict)
        else {}
    )
    db_fallbacks: dict[str, str] = {
        "bangumi_token": str(
            (db_cfg or {}).get("bangumi_token") or db_api_keys.get("bangumi") or ""
        ).strip(),
        "touchgal_api_key": str(db_api_keys.get("touchgal") or "").strip(),
        "steamgriddb_api_key": str(db_api_keys.get("steamgriddb") or "").strip(),
        "ymgal_client_id": str(db_api_keys.get("ymgal_client_id") or "").strip(),
        "ymgal_client_secret": str(db_api_keys.get("ymgal_client_secret") or "").strip(),
        "kungal_token": str(db_api_keys.get("kungal_token") or "").strip(),
        "igdb_client_id": str(db_api_keys.get("igdb_client_id") or "").strip(),
        "igdb_client_secret": str(db_api_keys.get("igdb_client_secret") or "").strip(),
    }

    for field in ALL_CREDENTIAL_FIELDS:
        if field in section and section[field] is not None:
            val = str(section[field]).strip()
        elif db_fallbacks.get(field):
            val = db_fallbacks[field]
        else:
            env_name = _ENV_FALLBACK_MAP.get(field, "")
            val = str(os.getenv(env_name, "") if env_name else "").strip()

        if field == "kungal_base_url" and not val:
            val = DEFAULT_KUNGAL_BASE_URL
        elif field == "touchgal_api_key":
            val = sanitize_touchgal_token(val)
        result[field] = val

    return result


def save_scraper_settings(
    updates: dict[str, Any],
    *,
    db_cfg: dict[str, Any] | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """
    更新并持久化刮削源配置至 DATA_DIR/settings.json。
    若敏感字段传入 None 或掩码占位符，则自动保留已有值；
    若显式传入空字符串 "" 或出现在 clear_fields 中，则清空该字段。
    """
    current = load_scraper_settings(db_cfg=db_cfg, path=path)
    clear_fields = set(updates.get("clear_fields") or [])

    if isinstance(updates.get("enabled_sources"), dict):
        next_enabled = dict(current["enabled_sources"])
        for src_id, flag in updates["enabled_sources"].items():
            norm_id = str(src_id).strip().lower()
            if norm_id in ALL_MANAGED_SCRAPER_IDS:
                next_enabled[norm_id] = bool(flag)
        current["enabled_sources"] = next_enabled

    for field in ALL_CREDENTIAL_FIELDS:
        if field in clear_fields:
            current[field] = DEFAULT_KUNGAL_BASE_URL if field == "kungal_base_url" else ""
            continue
        if field not in updates:
            continue
        raw_val = updates.get(field)
        if raw_val is None:
            continue
        val = str(raw_val).strip()
        if field in SECRET_CREDENTIAL_FIELDS and is_masked_placeholder(val):
            # 保留现有真实凭证
            continue
        if field == "kungal_base_url":
            current[field] = val.rstrip("/") if val else DEFAULT_KUNGAL_BASE_URL
        elif field == "touchgal_api_key":
            current[field] = sanitize_touchgal_token(val)
        else:
            current[field] = val

    full_doc = _read_raw_json(path)
    full_doc["scraper_sources"] = current
    _write_raw_json(full_doc, path=path)
    return current


def is_source_configured(source_id: str, settings: dict[str, Any]) -> bool:
    sid = source_id.strip().lower()
    if sid in FREE_SCRAPER_IDS:
        return True
    if sid == "touchgal":
        return bool(str(settings.get("touchgal_api_key") or "").strip())
    if sid == "steamgriddb":
        return bool(str(settings.get("steamgriddb_api_key") or "").strip())
    if sid == "igdb":
        return bool(
            str(settings.get("igdb_client_id") or "").strip()
            and str(settings.get("igdb_client_secret") or "").strip()
        )
    return False


def mask_scraper_settings_for_client(settings: dict[str, Any]) -> dict[str, Any]:
    """构造返回给前端的脱敏配置对象（绝不泄露明文密钥）"""
    masked: dict[str, Any] = {
        "enabled_sources": dict(settings.get("enabled_sources") or {}),
        "ymgal_client_id": str(settings.get("ymgal_client_id") or ""),
        "ymgal_client_secret": mask_secret(str(settings.get("ymgal_client_secret") or "")),
        "kungal_base_url": str(settings.get("kungal_base_url") or DEFAULT_KUNGAL_BASE_URL),
        "kungal_token": mask_secret(str(settings.get("kungal_token") or "")),
        "bangumi_token": mask_secret(str(settings.get("bangumi_token") or "")),
        "touchgal_api_key": mask_secret(str(settings.get("touchgal_api_key") or "")),
        "steamgriddb_api_key": mask_secret(str(settings.get("steamgriddb_api_key") or "")),
        "igdb_client_id": str(settings.get("igdb_client_id") or ""),
        "igdb_client_secret": mask_secret(str(settings.get("igdb_client_secret") or "")),
        "configured_secrets": {
            field: bool(str(settings.get(field) or "").strip())
            for field in SECRET_CREDENTIAL_FIELDS
        },
        "source_status": {
            sid: {
                "enabled": bool((settings.get("enabled_sources") or {}).get(sid, True)),
                "configured": is_source_configured(sid, settings),
                "requires_key": sid in KEY_SCRAPER_IDS,
            }
            for sid in ALL_MANAGED_SCRAPER_IDS
        },
        "settings_file": str((DATA_DIR / "settings.json").name),
    }
    return masked
