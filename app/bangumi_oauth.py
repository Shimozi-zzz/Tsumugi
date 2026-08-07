"""Bangumi OAuth 授权（连接 Bangumi 账号，用于批量导入收藏）

设计（详见 ADR 0022）：
- client_id/client_secret：用环境变量占位符 `BANGUMI_CLIENT_ID`/`SECRET`
  配置（复用 Provider/Connector 的"不落明文"模式：设置页填写 → 写入 .env，
  DB 不落明文）；
- access_token/refresh_token：动态获取的密钥无法用环境变量占位符表达，
  存到 `data/bangumi_tokens.json`（gitignored，与 .env 同一信任模型：DB 不落
  明文）；
- 过期处理：`get_valid_access_token` 在临近过期时自动 refresh；refresh 失败
  （token 被撤销/无效）抛 `NeedsReauthError`，前端提示"需要重新授权"而非静默
  失败；
- SSRF：token 兑换/刷新请求目标（bgm.tv）过 `check_ssrf_target` 校验。
"""
import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional

import httpx

from app.config import settings
from app.connectors.ssrf import SSRFError, check_ssrf_target

AUTHORIZE_URL = "https://bgm.tv/oauth/authorize"
TOKEN_URL = "https://bgm.tv/oauth/access_token"

CLIENT_ID_ENV = "BANGUMI_CLIENT_ID"
CLIENT_SECRET_ENV = "BANGUMI_CLIENT_SECRET"
TOKENS_FILE = Path(settings.upload_dir).parent / "bangumi_tokens.json"

_pending_state: Optional[str] = None


class OAuthError(Exception):
    """OAuth 流程错误，message 可直接展示给用户。"""


class NeedsReauthError(OAuthError):
    """需要重新授权（未连接 / 已过期 / 刷新失败）。"""


# ---------------------------------------------------------------- 客户端凭证

def get_client_credentials() -> tuple[str, str]:
    client_id = os.environ.get(CLIENT_ID_ENV, "").strip()
    client_secret = os.environ.get(CLIENT_SECRET_ENV, "").strip()
    if not client_id or not client_secret:
        raise OAuthError(
            "未配置 Bangumi 应用凭证。请先在 Bangumi 开发者后台注册应用，"
            "然后在设置页填入 client_id / client_secret（会自动写入 .env，不落库）。"
        )
    return client_id, client_secret


def save_client_config(client_id: str, client_secret: str) -> None:
    """把应用凭证写入 .env（复用 write_secret_to_env，不落库明文）。"""
    from app.providers import write_secret_to_env
    if not client_id.strip() or not client_secret.strip():
        raise OAuthError("client_id 与 client_secret 均不能为空")
    write_secret_to_env(CLIENT_ID_ENV, client_id)
    write_secret_to_env(CLIENT_SECRET_ENV, client_secret)


def is_config_configured() -> bool:
    return bool(os.environ.get(CLIENT_ID_ENV, "").strip()) and bool(os.environ.get(CLIENT_SECRET_ENV, "").strip())


# ---------------------------------------------------------------- 令牌存储（不落库明文）

def _load_tokens() -> Optional[dict]:
    if not TOKENS_FILE.exists():
        return None
    try:
        data = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _save_tokens(tokens: dict) -> None:
    TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKENS_FILE.write_text(json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(TOKENS_FILE, 0o600)
    except OSError:
        pass  # Windows 权限模型不同，尽力即可


def _clear_tokens() -> None:
    try:
        TOKENS_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def is_connected() -> bool:
    return _load_tokens() is not None


def get_connected_user() -> Optional[dict]:
    t = _load_tokens()
    if not t:
        return None
    uid = t.get("user_id")
    return {"user_id": str(uid) if uid is not None else None, "username": t.get("username")}


def get_username_from_tokens() -> Optional[str]:
    t = _load_tokens()
    return (t or {}).get("username")


def save_username(username: str) -> None:
    """缓存 Bangumi 用户名（收藏接口 /v0/users/{username}/collections 需要）。"""
    tokens = _load_tokens() or {}
    tokens["username"] = username
    _save_tokens(tokens)


def get_tokens() -> Optional[dict]:
    return _load_tokens()


# ---------------------------------------------------------------- 授权流程

def _check_token_url() -> None:
    """对 token 兑换/刷新端点做 SSRF 校验（bgm.tv 公网，正常通过）。"""
    try:
        check_ssrf_target(TOKEN_URL, resolve=True)
    except SSRFError as e:
        raise OAuthError(f"Bangumi token 端点地址不安全：{e}") from e


def build_authorize_url(redirect_uri: str) -> str:
    """构造授权跳转 URL。state 会暂存，回调时校验防 CSRF。"""
    global _pending_state
    _check_token_url()
    client_id, _ = get_client_credentials()
    import urllib.parse
    state = secrets.token_urlsafe(16)
    _pending_state = state
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def _post_token(data: dict, proxy: Optional[str]) -> dict:
    _check_token_url()
    try:
        resp = httpx.post(TOKEN_URL, data=data, timeout=20.0,
                          proxy=proxy or None,
                          headers={"User-Agent": "Tsumugi/0.1 (personal knowledge base)"})
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise OAuthError(f"Bangumi 授权服务器返回 {e.response.status_code}：{e.response.text[:200]}") from e
    except httpx.HTTPError as e:
        raise OAuthError(f"连接 Bangumi 授权服务器失败：{e}") from e


def exchange_code(code: str, redirect_uri: str, state: Optional[str] = None) -> dict:
    """用授权码换取 access_token（校验 state 防 CSRF）。"""
    global _pending_state
    if state and _pending_state and state != _pending_state:
        raise OAuthError("授权 state 校验失败，请重新发起授权")
    client_id, client_secret = get_client_credentials()
    proxy = _bangumi_proxy()
    payload = _post_token({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }, proxy)
    if not payload.get("access_token"):
        raise OAuthError("授权响应缺少 access_token，请重试或重新授权")
    tokens = {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token", ""),
        "user_id": payload.get("user_id"),
        "expires_at": int(time.time()) + int(payload.get("expires_in", 0) or 0) - 60,
    }
    _save_tokens(tokens)
    _pending_state = None
    return tokens


def refresh_access_token() -> dict:
    """用 refresh_token 刷新；失败抛 NeedsReauthError（前端提示重新授权）。"""
    tokens = _load_tokens()
    if not tokens or not tokens.get("refresh_token"):
        raise NeedsReauthError("Bangumi 未连接或缺少 refresh_token，请重新授权")
    client_id, client_secret = get_client_credentials()
    proxy = _bangumi_proxy()
    try:
        payload = _post_token({
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": tokens["refresh_token"],
        }, proxy)
    except OAuthError as e:
        raise NeedsReauthError(f"Bangumi 授权刷新失败，请重新授权：{e}") from e
    if not payload.get("access_token"):
        raise NeedsReauthError("Bangumi 授权已失效，请重新授权")
    tokens["access_token"] = payload["access_token"]
    if payload.get("refresh_token"):
        tokens["refresh_token"] = payload["refresh_token"]
    tokens["expires_at"] = int(time.time()) + int(payload.get("expires_in", 0) or 0) - 60
    _save_tokens(tokens)
    return tokens


def get_valid_access_token() -> str:
    """返回可用的 access_token（临近过期自动刷新）。"""
    tokens = _load_tokens()
    if not tokens or not tokens.get("access_token"):
        raise NeedsReauthError("Bangumi 未连接，请先在设置页完成授权")
    if int(tokens.get("expires_at", 0)) > int(time.time()) + 60:
        return tokens["access_token"]
    refreshed = refresh_access_token()
    return refreshed["access_token"]


def disconnect() -> None:
    _clear_tokens()
    _pending_state = None


def _bangumi_proxy() -> Optional[str]:
    from app.connectors import registry
    return registry.get_proxy("bangumi")
