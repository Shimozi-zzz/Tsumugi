"""UI 直接填真实 Key：保存时写入 .env、存占位符、不落库明文；与占位符方式并存。"""
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import providers
from app.api.routes import router
from app.database import get_db


class _FakeResp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=self)


@pytest.fixture(scope="function")
def client(db, fake_collection, patch_embeddings, monkeypatch, tmp_path):
    from app import provider_store  # noqa: F401  确保 store 模块已加载
    monkeypatch.setattr(providers, "SECRET_ENV_PATH", tmp_path / ".env")
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    for k in list(os.environ):
        if k.startswith("TSUMUGI_API_KEY_"):
            monkeypatch.delenv(k, raising=False)


def _payload(name="deepseek", key=None, enabled=False):
    return {
        "name": name, "provider_type": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1", "model_id": "deepseek-chat",
        "api_key_ref": key, "enabled": enabled,
    }


class TestPlaintextKeySave:
    def test_save_plaintext_writes_env_and_placeholder(self, client, tmp_path):
        r = client.post("/api/llm/providers", json=_payload(key="sk-real-secret-123"))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["api_key_ref"] == "{TSUMUGI_API_KEY_DEEPSEEK}"
        # 响应与库中都不出现明文
        assert "sk-real-secret-123" not in json.dumps(data)
        # .env 已写入且可解析
        env = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "TSUMUGI_API_KEY_DEEPSEEK=sk-real-secret-123" in env
        assert providers._resolve_env_placeholder("{TSUMUGI_API_KEY_DEEPSEEK}") == "sk-real-secret-123"

    def test_save_placeholder_keeps_reference(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")
        r = client.post("/api/llm/providers", json=_payload(key="{DEEPSEEK_API_KEY}"))
        assert r.status_code == 200
        assert r.json()["api_key_ref"] == "{DEEPSEEK_API_KEY}"
        # 占位符路径不写 .env
        assert not (tmp_path / ".env").exists()

    def test_two_providers_do_not_interfere(self, client):
        r1 = client.post("/api/llm/providers", json=_payload(name="a", key="key-A"))
        r2 = client.post("/api/llm/providers", json=_payload(name="b", key="key-B"))
        assert r1.json()["api_key_ref"] == "{TSUMUGI_API_KEY_A}"
        assert r2.json()["api_key_ref"] == "{TSUMUGI_API_KEY_B}"
        refs = {p["name"]: p["api_key_ref"] for p in client.get("/api/llm/providers").json()["providers"]}
        assert refs["a"] == "{TSUMUGI_API_KEY_A}"
        assert refs["b"] == "{TSUMUGI_API_KEY_B}"
        assert providers._resolve_env_placeholder(refs["a"]) == "key-A"
        assert providers._resolve_env_placeholder(refs["b"]) == "key-B"

    def test_malformed_placeholder_rejected(self, client):
        r = client.post("/api/llm/providers", json=_payload(key="{BAD"))
        assert r.status_code == 400
        assert "占位符" in r.json()["detail"]

    def test_test_connection_with_plaintext(self, client, monkeypatch):
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None, **kw):
            captured["auth"] = (headers or {}).get("Authorization")
            return _FakeResp(200, {"choices": [{"message": {"content": "pong"}}]})

        monkeypatch.setattr("app.providers.httpx.post", fake_post)
        r = client.post("/api/llm/test", json={
            "provider_type": "openai_compatible",
            "base_url": "https://api.deepseek.com/v1", "model_id": "deepseek-chat",
            "api_key_ref": "sk-temporary",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert captured["auth"] == "Bearer sk-temporary"

    def test_test_connection_placeholder_uses_env(self, client, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None, **kw):
            captured["auth"] = (headers or {}).get("Authorization")
            return _FakeResp(200, {"choices": [{"message": {"content": "pong"}}]})

        monkeypatch.setattr("app.providers.httpx.post", fake_post)
        r = client.post("/api/llm/test", json={
            "provider_type": "openai_compatible",
            "base_url": "https://api.deepseek.com/v1", "model_id": "deepseek-chat",
            "api_key_ref": "{DEEPSEEK_API_KEY}",
        })
        assert r.status_code == 200
        assert captured["auth"] == "Bearer from-env"
