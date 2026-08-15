"""SSRF 防护测试：协议校验、内网/回环拒绝、DNS 解析校验、合法公网放行"""
import socket

import pytest

from app.connectors.base import DeclarativeConnector
from app.connectors.ssrf import SSRFError, check_ssrf_target


def _config(base_url, **over):
    cfg = {
        "name": "my-api", "display_name": "My",
        "base_url": base_url,
        "search_endpoint": "/search?q={query}",
        "field_map": {"title": "title", "external_id": "id"},
    }
    cfg.update(over)
    return cfg


class TestProtocol:
    def test_rejects_non_http(self):
        with pytest.raises(SSRFError):
            check_ssrf_target("file:///etc/passwd", resolve=False)
        with pytest.raises(SSRFError):
            check_ssrf_target("ftp://example.com/x", resolve=False)
        with pytest.raises(SSRFError):
            check_ssrf_target("//no-scheme", resolve=False)

    def test_allows_https(self):
        check_ssrf_target("https://api.example.com/x", resolve=False)  # 不抛异常


class TestIpLiteral:
    @pytest.mark.parametrize("url", [
        "http://127.0.0.1:8000/x",
        "http://localhost/x",
        "http://10.0.0.1/x",
        "http://172.16.0.1/x",
        "http://192.168.1.1/x",
        "http://169.254.169.254/latest/meta-data",  # 云元数据
        "http://0.0.0.0/x",
    ])
    def test_rejects_private_ip(self, url):
        with pytest.raises(SSRFError):
            check_ssrf_target(url, resolve=False)

    def test_allows_public_ip(self):
        check_ssrf_target("http://8.8.8.8/x", resolve=False)

    def test_allows_public_domain(self):
        # 创建时 resolve=False 对域名不做解析，直接放行（请求时才解析）
        check_ssrf_target("https://api.example.com/x", resolve=False)


class TestCreationValidation:
    def test_create_rejects_internal_ip(self):
        with pytest.raises(ValueError, match="配置不安全"):
            DeclarativeConnector(_config("http://127.0.0.1:9000"))

    def test_create_rejects_localhost(self):
        with pytest.raises(ValueError, match="配置不安全"):
            DeclarativeConnector(_config("http://localhost:9000"))

    def test_create_rejects_private_range(self):
        with pytest.raises(ValueError, match="配置不安全"):
            DeclarativeConnector(_config("http://192.168.1.10"))

    def test_create_allows_public(self):
        c = DeclarativeConnector(_config("https://api.example.com"))
        assert c.name == "my-api"


class TestSearchResolution:
    def test_search_rejects_domain_resolving_to_internal(self, monkeypatch):
        # 模拟域名解析到内网 IP（DNS rebinding 场景）
        def fake_getaddrinfo(host, port):
            return [(2, 1, 6, "", ("169.254.169.254", 0))]
        monkeypatch.setattr("app.connectors.ssrf.socket.getaddrinfo", fake_getaddrinfo)

        c = DeclarativeConnector(_config("http://metadata.example.com"))
        from app.connectors.base import ConnectorError
        with pytest.raises(ConnectorError, match="目标地址不安全"):
            c.search("关键词")

    def test_search_resolution_failure(self, monkeypatch):
        def fake_getaddrinfo(host, port):
            raise socket.gaierror("无法解析")
        monkeypatch.setattr("app.connectors.ssrf.socket.getaddrinfo", fake_getaddrinfo)
        c = DeclarativeConnector(_config("http://no-such.example.com"))
        from app.connectors.base import ConnectorError
        with pytest.raises(ConnectorError):
            c.search("关键词")
