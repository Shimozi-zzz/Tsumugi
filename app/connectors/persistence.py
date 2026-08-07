"""声明式 Connector 配置持久化（Phase 4）

用户通过管理 API 创建的自定义数据源配置保存在 sources 表（config_ref 存 JSON，
密钥部分引用环境变量名，不落库明文）。启动时自动加载恢复注册。
"""
import json
from typing import List, Optional

from app.models import Source


def _session():
    # 函数体内 import：与 routes._ingest_sync 一致，测试 patch 时能覆盖
    from app.database import SessionLocal
    return SessionLocal()
def save_declarative_config(config: dict, enabled: bool = True) -> Source:
    """持久化声明式配置到 sources 表（type=connector）。同名覆盖。"""
    db = _session()
    try:
        src = (
            db.query(Source).filter(Source.name == config["name"]).first()
        )
        if src is None:
            src = Source(name=config["name"], type="connector")
            db.add(src)
        # 密钥占位：config 里的 headers 若含 {env_var}，不落明文，
        # 运行时从环境变量解析。这里整体存 JSON，风险由"占位符约定"控制。
        src.config_ref = json.dumps(config, ensure_ascii=False)
        src.enabled = 1 if enabled else 0
        db.commit()
        db.refresh(src)
        return src
    finally:
        db.close()


def load_declarative_configs() -> List[dict]:
    """从 sources 表加载所有 connector 类型配置。"""
    db = _session()
    try:
        rows = db.query(Source).filter(Source.type == "connector").all()
        configs = []
        for row in rows:
            try:
                config = json.loads(row.config_ref or "{}")
                config["_enabled"] = bool(row.enabled)
                configs.append(config)
            except json.JSONDecodeError:
                continue
        return configs
    finally:
        db.close()


def delete_declarative_config(name: str) -> bool:
    db = _session()
    try:
        src = db.query(Source).filter(Source.name == name).first()
        if src is None:
            return False
        db.delete(src)
        db.commit()
        return True
    finally:
        db.close()


# ---------------------------------------------------------------- Connector 通用设置（出站代理）

# sources 表里保存"全量 connector 设置"的固定行名（避免与任意 connector 名冲突，
# 因为 Source.name 是唯一键，声明式数据源已占用各自 name 的行）。
_SETTINGS_ROW = "connector_settings"
_SETTINGS_TYPE = "settings"


def get_connector_settings() -> dict:
    """读取所有 Connector 的通用设置（当前为出站代理）。

    返回 {connector_name: {"proxy_url": "..."}}，无设置则空 dict。
    """
    db = _session()
    try:
        row = db.query(Source).filter(
            Source.name == _SETTINGS_ROW, Source.type == _SETTINGS_TYPE
        ).first()
        if row is None or not row.config_ref:
            return {}
        try:
            data = json.loads(row.config_ref)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    finally:
        db.close()


def save_connector_proxy(name: str, proxy_url: str) -> None:
    """保存某 Connector 的出站代理（空串=清除，即直连）。"""
    settings = get_connector_settings()
    proxy_url = (proxy_url or "").strip()
    if proxy_url:
        settings[name] = {"proxy_url": proxy_url}
    else:
        settings.pop(name, None)
    db = _session()
    try:
        row = db.query(Source).filter(
            Source.name == _SETTINGS_ROW, Source.type == _SETTINGS_TYPE
        ).first()
        if row is None:
            row = Source(name=_SETTINGS_ROW, type=_SETTINGS_TYPE)
            db.add(row)
        row.config_ref = json.dumps(settings, ensure_ascii=False)
        row.enabled = 1
        db.commit()
    finally:
        db.close()
