"""第三方插件加载测试（ADR 0027：本地文件信任模型）

覆盖：正常加载 / 语法错误优雅跳过 / 缺 build_connector / 接口不符合 /
名字冲突 / _ 前缀目录跳过 / 端到端参与联合检索 / 风险确认端点。
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import plugins
from app.api.routes import router
from app.config import settings
from app.connectors import registry
from app.database import get_db

VALID_MANIFEST = {
    "name": "helloconn",
    "display_name": "Hello 示例数据源",
    "version": "0.1.0",
    "auth_type": "none",
    "base_url": "https://example.com",
    "rate_limit": {"requests_per_minute": 10},
    "capabilities": ["search", "get_detail"],
}

VALID_CONNECTOR = '''\
"""最小示例插件：直接复制修改即可（详见 plugins/README.md）。"""
from app.connectors.base import ItemDetail, SearchResult


class HelloConnector:
    """实现 Connector Protocol 的 search/get_detail（name/manifest 由 manifest.json 注入）。"""

    name = ""
    manifest = None

    def search(self, query, **filters):
        if not query or not query.strip():
            return []
        return [
            SearchResult(
                source=self.name,
                title=f"Hello: {query.strip()}",
                external_id="hello-1",
                description="来自示例插件的数据源结果。",
            )
        ]

    def get_detail(self, external_id):
        return ItemDetail(
            source=self.name, title="Hello 详情", external_id=external_id,
            description="示例详情。",
        )


def build_connector():
    return HelloConnector()
'''


def _write_plugin(root, name, manifest=None, connector_code=None):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(
        json.dumps(manifest or VALID_MANIFEST, ensure_ascii=False), encoding="utf-8"
    )
    (d / "connector.py").write_text(
        connector_code if connector_code is not None else VALID_CONNECTOR,
        encoding="utf-8",
    )
    return d


@pytest.fixture()
def plugin_env(tmp_path, monkeypatch):
    """把插件目录指到临时目录，并在测试后清理插件注册残留。"""
    monkeypatch.setattr(settings, "plugins_dir", str(tmp_path))
    yield tmp_path
    # 清理本测试注册的插件（registry 是模块级全局）
    for c in registry.list_plugin_connectors():
        registry.unregister(c.name)


class TestLoadPlugins:
    def test_loads_valid_plugin(self, plugin_env):
        _write_plugin(plugin_env, "helloconn")
        result = plugins.load_plugins()
        assert result["failures"] == []
        loaded = {p["name"] for p in result["loaded"]}
        assert "helloconn" in loaded
        conn = registry.get_connector("helloconn")
        assert conn is not None
        assert registry.get_origin("helloconn") == "plugin"
        assert conn.manifest.name == "helloconn"  # manifest.json 是权威
        hits = conn.search("测试")
        assert hits and hits[0].title == "Hello: 测试"

    def test_plugin_participates_in_federated_search(
        self, plugin_env, db, fake_collection, patch_embeddings
    ):
        _write_plugin(plugin_env, "helloconn")
        plugins.load_plugins()
        # 只保留插件，避免其它测试残留的 connector 发真实请求
        for m in registry.list_manifests():
            if m.name != "helloconn":
                registry.unregister(m.name)

        app = FastAPI()
        app.include_router(router, prefix="/api")

        def override_db():
            yield db

        app.dependency_overrides[get_db] = override_db
        c = TestClient(app)
        r = c.post("/api/search/federated", json={"query": "任意关键词"})
        assert r.status_code == 200, r.text
        sources = {x["source"] for x in r.json()["results"]}
        assert "helloconn" in sources

    def test_underscore_dir_skipped(self, plugin_env):
        _write_plugin(plugin_env / "_template", "hello_template")
        result = plugins.load_plugins()
        assert result["loaded"] == []
        assert result["failures"] == []

    def test_no_plugins_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "plugins_dir", str(tmp_path / "nope"))
        result = plugins.load_plugins()
        assert result["loaded"] == []
        assert result["failures"] == []


class TestLoadFailures:
    """单个插件失败优雅跳过，不影响其它插件与应用启动。"""

    def test_syntax_error_skipped(self, plugin_env):
        _write_plugin(plugin_env, "bad_syntax", connector_code="def broken(:\n")
        _write_plugin(plugin_env, "helloconn")
        result = plugins.load_plugins()
        assert registry.get_connector("bad_syntax") is None
        assert registry.get_connector("helloconn") is not None  # 其它插件照常加载
        failures = {f["dir"] for f in result["failures"]}
        assert "bad_syntax" in failures

    def test_missing_build_connector_skipped(self, plugin_env):
        _write_plugin(plugin_env, "no_build", connector_code="CONN = 1\n")
        result = plugins.load_plugins()
        assert registry.get_connector("no_build") is None
        assert any(f["dir"] == "no_build" for f in result["failures"])

    def test_build_returns_none_skipped(self, plugin_env):
        _write_plugin(plugin_env, "none_conn",
                      connector_code="def build_connector():\n    return None\n")
        result = plugins.load_plugins()
        assert registry.get_connector("none_conn") is None
        assert any(f["dir"] == "none_conn" for f in result["failures"])

    def test_missing_search_skipped(self, plugin_env):
        _write_plugin(plugin_env, "no_search",
                      connector_code="def build_connector():\n    return object()\n")
        result = plugins.load_plugins()
        assert registry.get_connector("no_search") is None
        assert any(f["dir"] == "no_search" for f in result["failures"])

    def test_declared_get_detail_but_missing_skipped(self, plugin_env):
        manifest = dict(VALID_MANIFEST)
        manifest["capabilities"] = ["search", "get_detail"]
        _write_plugin(plugin_env, "no_detail", manifest=manifest, connector_code='''\
from app.connectors.base import SearchResult
class C:
    name = "no_detail"
    manifest = None
    def search(self, query, **filters):
        return [SearchResult(source=self.name, title="x", external_id="1")]
def build_connector():
    return C()
''')
        result = plugins.load_plugins()
        assert registry.get_connector("no_detail") is None
        assert any(f["dir"] == "no_detail" for f in result["failures"])

    def test_name_conflict_skipped(self, plugin_env):
        class FakeBuiltin:
            name = "helloconn"
            manifest = None
            proxy_url = None

        registry.register(FakeBuiltin(), enabled=True)  # 同名内置先注册
        try:
            _write_plugin(plugin_env, "helloconn")
            result = plugins.load_plugins()
            assert registry.get_origin("helloconn") == "builtin"  # 插件未覆盖
            assert any(f["dir"] == "helloconn" for f in result["failures"])
        finally:
            registry.unregister("helloconn")

    def test_invalid_manifest_json_skipped(self, plugin_env):
        d = plugin_env / "bad_manifest"
        d.mkdir()
        (d / "manifest.json").write_text("{ not json", encoding="utf-8")
        (d / "connector.py").write_text("x = 1\n", encoding="utf-8")
        result = plugins.load_plugins()
        assert registry.get_connector("bad_manifest") is None
        assert any(f["dir"] == "bad_manifest" for f in result["failures"])


class TestPluginEndpoints:
    def test_plugins_endpoint_and_notice(self, plugin_env, db):
        _write_plugin(plugin_env, "helloconn")
        plugins.load_plugins()

        app = FastAPI()
        app.include_router(router, prefix="/api")

        def override_db():
            yield db

        app.dependency_overrides[get_db] = override_db
        c = TestClient(app)

        # 有插件且未确认 → notice_needed=True
        r = c.get("/api/plugins")
        assert r.status_code == 200
        body = r.json()
        assert body["notice_needed"] is True
        assert any(p["name"] == "helloconn" for p in body["plugins"])
        assert body["plugin_dir"].endswith("plugins") or body["plugin_dir"]

        # 确认后 → notice_needed=False
        assert c.post("/api/plugins/acknowledge").status_code == 200
        assert c.get("/api/plugins").json()["notice_needed"] is False

    def test_connectors_endpoint_marks_origin(self, plugin_env, db):
        _write_plugin(plugin_env, "helloconn")
        plugins.load_plugins()
        app = FastAPI()
        app.include_router(router, prefix="/api")

        def override_db():
            yield db

        app.dependency_overrides[get_db] = override_db
        r = TestClient(app).get("/api/connectors").json()
        entry = next((x for x in r if x["name"] == "helloconn"), None)
        assert entry is not None
        assert entry["origin"] == "plugin"
