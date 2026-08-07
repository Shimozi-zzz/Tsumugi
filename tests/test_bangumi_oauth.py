"""Bangumi OAuth：凭证配置、授权码兑换、刷新、过期处理（mock 网络）"""
import json
import time

import httpx
import pytest

from app import bangumi_oauth


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setattr(bangumi_oauth, "TOKENS_FILE", tmp_path / "tokens.json")
    monkeypatch.delenv(bangumi_oauth.CLIENT_ID_ENV, raising=False)
    monkeypatch.delenv(bangumi_oauth.CLIENT_SECRET_ENV, raising=False)
    yield


class TestClientConfig:
    def test_save_client_config_writes_env(self, monkeypatch, tmp_path):
        from app import providers
        monkeypatch.setattr(providers, "SECRET_ENV_PATH", tmp_path / ".env")
        bangumi_oauth.save_client_config("id123", "secret456")
        env = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "BANGUMI_CLIENT_ID=id123" in env
        assert "BANGUMI_CLIENT_SECRET=secret456" in env
        assert bangumi_oauth.is_config_configured()

    def test_empty_config_rejected(self):
        with pytest.raises(bangumi_oauth.OAuthError):
            bangumi_oauth.save_client_config("", "x")

    def test_missing_credentials_error(self):
        with pytest.raises(bangumi_oauth.OAuthError, match="注册"):
            bangumi_oauth.get_client_credentials()


class TestAuthorizeUrl:
    def test_build_authorize_url(self, monkeypatch):
        monkeypatch.setenv(bangumi_oauth.CLIENT_ID_ENV, "cid")
        monkeypatch.setenv(bangumi_oauth.CLIENT_SECRET_ENV, "csec")
        url = bangumi_oauth.build_authorize_url("http://127.0.0.1:8001/api/bangumi/oauth/callback")
        assert url.startswith("https://bgm.tv/oauth/authorize?")
        assert "client_id=cid" in url
        assert "response_type=code" in url
        assert "redirect_uri=" in url
        assert "state=" in url

    def test_build_authorize_url_requires_config(self):
        with pytest.raises(bangumi_oauth.OAuthError):
            bangumi_oauth.build_authorize_url("http://x")


class TestExchangeAndRefresh:
    def _mock_post(self, monkeypatch, payload):
        def fake_post(url, data=None, **kw):
            assert url == bangumi_oauth.TOKEN_URL
            return _FakeResp(200, payload)
        monkeypatch.setattr(bangumi_oauth.httpx, "post", fake_post)

    def test_exchange_code_saves_tokens(self, monkeypatch):
        monkeypatch.setenv(bangumi_oauth.CLIENT_ID_ENV, "cid")
        monkeypatch.setenv(bangumi_oauth.CLIENT_SECRET_ENV, "csec")
        self._mock_post(monkeypatch, {
            "access_token": "acc", "refresh_token": "ref", "expires_in": 3600, "user_id": "u1",
        })
        tokens = bangumi_oauth.exchange_code("the-code", "http://127.0.0.1:8001/api/bangumi/oauth/callback")
        assert tokens["access_token"] == "acc"
        assert bangumi_oauth.is_connected()
        assert bangumi_oauth.get_valid_access_token() == "acc"
        assert bangumi_oauth.get_connected_user()["user_id"] == "u1"

    def test_state_mismatch_rejected(self, monkeypatch):
        monkeypatch.setenv(bangumi_oauth.CLIENT_ID_ENV, "cid")
        monkeypatch.setenv(bangumi_oauth.CLIENT_SECRET_ENV, "csec")
        bangumi_oauth._pending_state = "expected-state"
        with pytest.raises(bangumi_oauth.OAuthError, match="state"):
            bangumi_oauth.exchange_code("code", "http://x", state="wrong")

    def test_auto_refresh_when_expired(self, monkeypatch):
        monkeypatch.setenv(bangumi_oauth.CLIENT_ID_ENV, "cid")
        monkeypatch.setenv(bangumi_oauth.CLIENT_SECRET_ENV, "csec")
        bangumi_oauth._save_tokens({
            "access_token": "old", "refresh_token": "ref",
            "user_id": "u1", "expires_at": int(time.time()) - 100,
        })
        self._mock_post(monkeypatch, {
            "access_token": "new-acc", "refresh_token": "new-ref",
            "expires_in": 3600, "user_id": "u1",
        })
        assert bangumi_oauth.get_valid_access_token() == "new-acc"
        assert bangumi_oauth.get_tokens()["refresh_token"] == "new-ref"

    def test_refresh_failure_raises_reauth(self, monkeypatch):
        monkeypatch.setenv(bangumi_oauth.CLIENT_ID_ENV, "cid")
        monkeypatch.setenv(bangumi_oauth.CLIENT_SECRET_ENV, "csec")
        bangumi_oauth._save_tokens({
            "access_token": "old", "refresh_token": "ref", "expires_at": int(time.time()) - 100,
        })
        def fake_post(url, data=None, **kw):
            raise httpx.HTTPStatusError("401", request=None, response=_FakeResp(401, {}))
        monkeypatch.setattr(bangumi_oauth.httpx, "post", fake_post)
        with pytest.raises(bangumi_oauth.NeedsReauthError, match="重新授权"):
            bangumi_oauth.get_valid_access_token()

    def test_not_connected_raises_reauth(self):
        with pytest.raises(bangumi_oauth.NeedsReauthError, match="未连接"):
            bangumi_oauth.get_valid_access_token()

    def test_disconnect(self, monkeypatch):
        bangumi_oauth._save_tokens({"access_token": "a", "refresh_token": "r", "expires_at": 999999})
        bangumi_oauth.disconnect()
        assert not bangumi_oauth.is_connected()


class _FakeResp:
    def __init__(self, status_code, json_payload):
        self.status_code = status_code
        self._json = json_payload

    def json(self):
        return self._json

    @property
    def text(self):
        return json.dumps(self._json)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=None, response=self)
