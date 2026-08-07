"""Connector 出站代理：SSRF 校验 + 请求路由 + registry/persistence + API"""
import pytest

from app.connectors import persistence as connector_persistence
from app.connectors import registry
from app.connectors.base import (
    ConnectorError, DeclarativeConnector, TokenBucket, validate_proxy_url,
)
from app.connectors.bangumi.connector import BangumiConnector


# ---------------------------------------------------------------- validate_proxy_url（SSRF）

class TestValidateProxy:
    def test_none_and_empty_pass(self):
        validate_proxy_url(None)
        validate_proxy_url("")
        validate_proxy_url("   ")

    @pytest.mark.parametrize("url", [
        "http://192.168.1.10:8080",     # 私网 C
        "http://10.0.0.5:3128",         # 私网 A
        "http://172.16.0.9:8080",       # 私网 B
        "http://169.254.169.254:80",    # 云元数据/链路本地
        "socks5://8.8.8.8:1080",        # 非 http/https
        "ftp://proxy.example.com:21",   # 非 http/https
    ])
    def test_rejects_unsafe_proxy(self, url):
        with pytest.raises(ConnectorError, match="代理地址不安全"):
            validate_proxy_url(url)

    @pytest.mark.parametrize("url", [
        "http://127.0.0.1:7890",   # Clash/V2Ray 默认监听（回环，放行）
        "http://127.0.0.1:10809",  # v2rayN 常见端口
        "http://localhost:7890",   # 本机主机名
        "http://[::1]:7890",       # IPv6 回环
        "http://8.8.8.8:8080",     # 公网 IP
    ])
    def test_allows_loopback_and_public_proxy(self, url):
        validate_proxy_url(url)  # 回环（本地代理默认监听）+ 公网均放行

    def test_loopback_can_be_opt_out(self):
        # 显式关掉放行时，回环仍被拒（保留"严格模式"入口）
        with pytest.raises(ConnectorError, match="代理地址不安全"):
            validate_proxy_url("http://127.0.0.1:7890", allow_loopback=False)

    def test_allows_public_ip_proxy(self):
        validate_proxy_url("http://8.8.8.8:8080")  # 公网 IP 放行

    def test_allows_public_domain_proxy(self, monkeypatch):
        import socket
        monkeypatch.setattr(
            "app.connectors.ssrf.socket.getaddrinfo",
            lambda host, port=None: [(2, 1, 6, "", ("8.8.8.8", 0))],
        )
        validate_proxy_url("http://proxy.example.com:8080")  # 域名解析为公网 → 放行

    def test_rejects_domain_resolving_internal(self, monkeypatch):
        import socket
        monkeypatch.setattr(
            "app.connectors.ssrf.socket.getaddrinfo",
            lambda host, port=None: [(2, 1, 6, "", ("169.254.169.254", 0))],
        )
        with pytest.raises(ConnectorError, match="代理地址不安全"):
            validate_proxy_url("http://evil-proxy.example.com:8080")


# ---------------------------------------------------------------- 请求路由（有代理 / 无代理）

class _FakeResp:
    def __init__(self, status_code, json_payload=None):
        self.status_code = status_code
        self._json = json_payload or {}

    def json(self):
        return self._json


class TestRequestRouting:
    def test_bangumi_direct_by_default(self, monkeypatch):
        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return _FakeResp(200, {"data": []})

        monkeypatch.setattr("app.connectors.base.httpx.post", fake_post)
        conn = BangumiConnector()
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
        conn.search("辉夜")
        assert "proxy" not in captured["kwargs"]

    def test_bangumi_uses_proxy_when_set(self, monkeypatch):
        captured = {}

        def fake_post(url, **kwargs):
            captured["kwargs"] = kwargs
            return _FakeResp(200, {"data": []})

        monkeypatch.setattr("app.connectors.base.httpx.post", fake_post)
        conn = BangumiConnector()
        conn.proxy_url = "http://proxy.example.com:7890"
        monkeypatch.setattr(conn._cache, "get", lambda k, ttl=600: None)
        conn.search("辉夜")
        assert captured["kwargs"]["proxy"] == "http://proxy.example.com:7890"

    def test_declarative_uses_inline_proxy(self, monkeypatch):
        captured = {}
        config = {
            "name": "my-api", "display_name": "My",
            "base_url": "https://api.example.com",
            "search_endpoint": "/search?q={query}",
            "field_map": {"title": "title", "external_id": "id"},
            "proxy_url": "http://proxy.example.com:8080",
        }

        def fake_get(url, **kwargs):
            captured["kwargs"] = kwargs
            return _FakeResp(200, {"results": [{"id": "1", "title": "x"}]})

        monkeypatch.setattr("app.connectors.base.httpx.get", fake_get)
        monkeypatch.setattr("app.connectors.ssrf.socket.getaddrinfo",
                            lambda host, port=None: [(2, 1, 6, "", ("8.8.8.8", 0))])
        conn = DeclarativeConnector(config)
        conn.search("q")
        assert captured["kwargs"]["proxy"] == "http://proxy.example.com:8080"
        assert conn.proxy_url == "http://proxy.example.com:8080"

    def test_declarative_inline_internal_proxy_rejected(self):
        config = {
            "name": "bad", "base_url": "https://api.example.com",
            "search_endpoint": "/s?q={query}",
            "field_map": {"title": "t", "external_id": "i"},
            "proxy_url": "http://192.168.1.99:8080",
        }
        with pytest.raises(ValueError, match="代理配置不安全"):
            DeclarativeConnector(config)


# ---------------------------------------------------------------- registry 设置注入

class TestRegistryProxy:
    def test_apply_settings_sets_proxy(self):
        conn = BangumiConnector()
        registry.register(conn)
        try:
            registry.apply_settings({"bangumi": {"proxy_url": "http://p.example.com:7890"}})
            assert conn.proxy_url == "http://p.example.com:7890"
            assert registry.get_proxy("bangumi") == "http://p.example.com:7890"

            registry.apply_settings({"bangumi": {"proxy_url": ""}})
            assert conn.proxy_url is None
        finally:
            registry.unregister("bangumi")

    def test_apply_settings_unknown_connector_ignored(self):
        registry.apply_settings({"no-such": {"proxy_url": "http://x:1"}})  # 不抛错


# ---------------------------------------------------------------- persistence（sources 表）

class TestProxyPersistence:
    def test_roundtrip_and_clear(self, db):
        connector_persistence.save_connector_proxy("bangumi", "http://proxy.example.com:7890")
        settings = connector_persistence.get_connector_settings()
        assert settings["bangumi"]["proxy_url"] == "http://proxy.example.com:7890"

        connector_persistence.save_connector_proxy("bangumi", "")  # 清除
        assert "bangumi" not in connector_persistence.get_connector_settings()

    def test_multiple_connectors(self, db):
        connector_persistence.save_connector_proxy("bangumi", "http://a:1")
        connector_persistence.save_connector_proxy("moegirl", "http://b:2")
        settings = connector_persistence.get_connector_settings()
        assert settings["bangumi"]["proxy_url"] == "http://a:1"
        assert settings["moegirl"]["proxy_url"] == "http://b:2"


# ---------------------------------------------------------------- 基础设施（复用/新增）

class TestSharedInfra:
    def test_token_bucket_acquire(self):
        b = TokenBucket(60)
        b.acquire()  # 不抛错即可

    def test_https_public_proxy_allowed(self):
        validate_proxy_url("https://8.8.8.8:8080")  # https 公网代理放行


# ---------------------------------------------------------------- API（保存/测试代理）

class TestProxyApi:
    @pytest.fixture(autouse=True)
    def _setup(self, db):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.routes import router
        from app.database import get_db

        app = FastAPI()
        app.include_router(router, prefix="/api")

        def override_get_db():
            yield db

        app.dependency_overrides[get_db] = override_get_db
        conn = BangumiConnector()
        registry.register(conn)
        try:
            self.client = TestClient(app)
            yield
        finally:
            registry.unregister("bangumi")

    def test_save_proxy_rejects_internal(self):
        r = self.client.post("/api/connectors/bangumi/proxy",
                             json={"proxy_url": "http://192.168.1.10:8080"})
        assert r.status_code == 400
        assert "代理地址不安全" in r.json()["detail"]
        # 不应写入
        assert "bangumi" not in connector_persistence.get_connector_settings()

    def test_save_proxy_accepts_loopback_clash_default(self):
        # Clash/V2Ray 默认监听 127.0.0.1:7890 —— 代理配置最主要的目标场景
        r = self.client.post("/api/connectors/bangumi/proxy",
                             json={"proxy_url": "http://127.0.0.1:7890"})
        assert r.status_code == 200, r.text
        assert r.json()["proxy_url"] == "http://127.0.0.1:7890"
        assert connector_persistence.get_connector_settings()["bangumi"]["proxy_url"] == "http://127.0.0.1:7890"
        r = self.client.post("/api/connectors/bangumi/proxy", json={"proxy_url": ""})
        assert r.status_code == 200

    def test_save_proxy_accepts_public_and_clears(self):
        r = self.client.post("/api/connectors/bangumi/proxy",
                             json={"proxy_url": "http://8.8.8.8:8080"})
        assert r.status_code == 200, r.text
        assert r.json()["proxy_url"] == "http://8.8.8.8:8080"
        assert connector_persistence.get_connector_settings()["bangumi"]["proxy_url"] == "http://8.8.8.8:8080"
        assert registry.get_proxy("bangumi") == "http://8.8.8.8:8080"

        r = self.client.post("/api/connectors/bangumi/proxy", json={"proxy_url": ""})
        assert r.status_code == 200
        assert registry.get_proxy("bangumi") is None

    def test_proxy_unknown_connector_404(self):
        r = self.client.post("/api/connectors/nope/proxy", json={"proxy_url": "http://8.8.8.8:8080"})
        assert r.status_code == 404

    def test_test_proxy_ok(self, monkeypatch):
        monkeypatch.setattr(
            "app.connectors.base.httpx.get",
            lambda url, **kwargs: _FakeResp(200),
        )
        r = self.client.post("/api/connectors/bangumi/test-proxy",
                             json={"proxy_url": "http://8.8.8.8:8080"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "通过代理连接成功" in body["message"]

    def test_test_proxy_loopback_passes_ssrf(self, monkeypatch):
        # 回环代理过 SSRF 校验（不再 400），进入真实连接阶段
        import httpx

        def fake_get(url, **kwargs):
            raise httpx.ConnectError("连接被拒绝")

        monkeypatch.setattr("app.connectors.base.httpx.get", fake_get)
        r = self.client.post("/api/connectors/bangumi/test-proxy",
                             json={"proxy_url": "http://127.0.0.1:7890"})
        assert r.status_code == 200  # 不因回环被拒
        body = r.json()
        assert body["ok"] is False
        assert "连接失败" in body["message"]

    def test_test_proxy_connection_failure(self, monkeypatch):
        import httpx

        def fake_get(url, **kwargs):
            raise httpx.ConnectError("连接被拒绝")

        monkeypatch.setattr("app.connectors.base.httpx.get", fake_get)
        r = self.client.post("/api/connectors/bangumi/test-proxy",
                             json={"proxy_url": "http://8.8.8.8:8080"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert "连接失败" in body["message"]
