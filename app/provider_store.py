"""LLM Provider 配置持久化

复用 Phase 4 Connector 的持久化模式（app/connectors/persistence.py）：
- 配置存独立表 llm_providers（结构化列 + api_key_ref 环境变量占位符，
  不落明文）；
- 同一时间仅一个 enabled=1（保存/切换时先清其它 enabled）；
- `_session()` 函数体内 import，测试 patch 可覆盖（坑位 #22 变体）。
"""
from typing import List, Optional

from app.models import LLMProviderConfig


def _session():
    from app.database import SessionLocal
    return SessionLocal()


def list_providers() -> List[dict]:
    """列出全部 provider 配置（不含密钥明文，仅返回占位符）。"""
    db = _session()
    try:
        rows = db.query(LLMProviderConfig).order_by(LLMProviderConfig.name).all()
        return [_row_to_dict(r) for r in rows]
    finally:
        db.close()


def _row_to_dict(r: LLMProviderConfig) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "provider_type": r.provider_type,
        "base_url": r.base_url,
        "model_id": r.model_id,
        "api_key_ref": r.api_key_ref,  # 占位符或 None，不下发明文
        "enabled": bool(r.enabled),
    }


def get_provider(name: str) -> Optional[dict]:
    for p in list_providers():
        if p["name"] == name:
            return p
    return None


def get_enabled_provider() -> Optional[dict]:
    db = _session()
    try:
        row = db.query(LLMProviderConfig).filter(LLMProviderConfig.enabled == 1).first()
        return _row_to_dict(row) if row else None
    finally:
        db.close()


def save_provider(
    name: str,
    provider_type: str,
    base_url: str,
    model_id: str,
    api_key_ref: Optional[str] = None,
    enabled: bool = False,
) -> dict:
    """保存/更新 provider 配置。name 唯一，存在则覆盖。"""
    db = _session()
    try:
        row = db.query(LLMProviderConfig).filter(LLMProviderConfig.name == name).first()
        if row is None:
            row = LLMProviderConfig(name=name)
            db.add(row)
        row.provider_type = provider_type
        row.base_url = base_url
        row.model_id = model_id
        row.api_key_ref = api_key_ref
        if enabled:
            # 同一时间仅一个启用：先清其它
            db.query(LLMProviderConfig).update(
                {LLMProviderConfig.enabled: 0}, synchronize_session=False
            )
            row.enabled = 1
        else:
            row.enabled = 0
        db.commit()
        db.refresh(row)
        return _row_to_dict(row)
    finally:
        db.close()


def set_enabled(name: str, enabled: bool) -> Optional[dict]:
    """启用/停用某 provider（启用时清其它）。"""
    db = _session()
    try:
        row = db.query(LLMProviderConfig).filter(LLMProviderConfig.name == name).first()
        if row is None:
            return None
        if enabled:
            db.query(LLMProviderConfig).update(
                {LLMProviderConfig.enabled: 0}, synchronize_session=False
            )
            row.enabled = 1
        else:
            row.enabled = 0
        db.commit()
        db.refresh(row)
        return _row_to_dict(row)
    finally:
        db.close()


def delete_provider(name: str) -> bool:
    db = _session()
    try:
        row = db.query(LLMProviderConfig).filter(LLMProviderConfig.name == name).first()
        if row is None:
            return False
        db.delete(row)
        db.commit()
        return True
    finally:
        db.close()
