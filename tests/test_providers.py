"""LLM Provider 抽象层 + 配置存储测试

覆盖：
- OpenAI 兼容 Provider（DeepSeek 预设）请求构造 + chat.completions 路径
- Ollama Provider（无 key、默认 base_url）
- provider_from_config 环境变量占位符解析
- test_connection mock HTTP
- provider_store CRUD + 单启用约束
- rag 降级（无 provider → AIAnswerDisabled）
"""
import json
import os

import httpx
import pytest

from app import provider_store, providers, rag
from app.models import LLMProviderConfig
from app.providers import (
    OpenAICompatibleProvider,
    OllamaProvider,
    ProviderError,
    provider_from_config,
)


class TestBuildRequest:
    def test_openai_compatible_uses_chat_completions(self):
        p = OpenAICompatibleProvider(
            name="deepseek", base_url="https://api.deepseek.com/v1",
            api_key="sk-test", model_id="deepseek-chat",
        )
        url, headers, body = p.build_request([{"role": "user", "content": "hi"}], stream=False)
        assert url == "https://api.deepseek.com/v1/chat/completions"
        assert url.endswith("/chat/completions")  # 关键：走 chat.completions 而非 responses
        assert headers["Authorization"] == "Bearer sk-test"
        assert body["model"] == "deepseek-chat"
        assert body["stream"] is False

    def test_ollama_no_api_key(self):
        p = OllamaProvider(name="ollama", model_id="qwen2.5:3b")
        url, headers, body = p.build_request([{"role": "user", "content": "hi"}], stream=True)
        assert url == "http://localhost:11434/v1/chat/completions"
        assert "Authorization" not in headers  # Ollama 无需 key
        assert body["stream"] is True
        assert body["model"] == "qwen2.5:3b"

    def test_missing_required_fields(self):
        with pytest.raises(ProviderError):
            OpenAICompatibleProvider(name="x", base_url="", model_id="")
        with pytest.raises(ProviderError):
            OllamaProvider(name="x", model_id="")


class TestProviderFromConfig:
    def test_env_placeholder_resolved(self, monkeypatch):
        monkeypatch.setenv("MY_LLM_KEY", "secret-env")
        cfg = {
            "name": "my", "provider_type": "openai_compatible",
            "base_url": "https://x/v1", "api_key_ref": "{MY_LLM_KEY}",
            "model_id": "m",
        }
        p = provider_from_config(cfg)
        assert p.api_key == "secret-env"

    def test_ollama_preset(self):
        cfg = {"name": "ollama", "provider_type": "ollama",
               "base_url": "http://localhost:11434/v1", "model_id": "qwen2.5:3b"}
        p = provider_from_config(cfg)
        assert isinstance(p, OllamaProvider)
        assert p.api_key is None


class TestConnectionFn:
    @pytest.fixture(autouse=True)
    def _mock_dns_public(self, monkeypatch):
        """SSRF 校验下，把测试域名的 DNS 解析 mock 为公网 IP。"""
        import socket
        monkeypatch.setattr(
            "app.connectors.ssrf.socket.getaddrinfo",
            lambda host, port=None: [(2, 1, 6, "", ("8.8.8.8", 0))],
        )

    def test_connection_success(self, monkeypatch):
        class FakeResp:
            status_code = 200
            text = ""
            def raise_for_status(self): pass
        monkeypatch.setattr(providers.httpx, "post", lambda *a, **k: FakeResp())
        msg = providers.test_connection({"name": "t", "provider_type": "openai_compatible",
                               "base_url": "https://api.example.com/v1", "model_id": "m", "api_key": None})
        assert "连接成功" in msg

    def test_connection_connect_error(self, monkeypatch):
        def boom(*a, **k):
            raise httpx.ConnectError("conn refused")
        monkeypatch.setattr(providers.httpx, "post", boom)
        with pytest.raises(ProviderError, match="连接失败"):
            providers.test_connection({"name": "t", "provider_type": "openai_compatible",
                             "base_url": "https://api.example.com/v1", "model_id": "m"})


class TestProviderStore:
    def test_crud(self, db):
        provider_store.save_provider("deepseek", "openai_compatible",
                                     "https://api.deepseek.com/v1", "deepseek-chat",
                                     api_key_ref="{DEEPSEEK_API_KEY}", enabled=True)
        provider_store.save_provider("ollama", "ollama",
                                     "http://localhost:11434/v1", "qwen2.5:3b", enabled=False)
        lst = provider_store.list_providers()
        assert len(lst) == 2
        # 只有 deepseek 启用
        assert provider_store.get_enabled_provider()["name"] == "deepseek"

    def test_single_enabled(self, db):
        provider_store.save_provider("a", "openai_compatible", "https://a/v1", "m1", enabled=True)
        provider_store.save_provider("b", "openai_compatible", "https://b/v1", "m2", enabled=True)
        # b 启用后 a 自动停用
        assert provider_store.get_enabled_provider()["name"] == "b"
        assert provider_store.get_provider("a")["enabled"] is False

    def test_switch_and_delete(self, db):
        provider_store.save_provider("a", "ollama", "http://localhost:11434/v1", "m", enabled=True)
        assert provider_store.set_enabled("a", False)["enabled"] is False
        assert provider_store.get_enabled_provider() is None
        assert provider_store.delete_provider("a") is True
        assert provider_store.delete_provider("a") is False
        assert provider_store.get_provider("a") is None

    def test_get_enabled_empty(self, db):
        assert provider_store.get_enabled_provider() is None


class TestProviderSSRF:
    """Provider base_url 的 SSRF 校验：Ollama 放行回环，通用 Provider 完整拦截。"""

    def test_ollama_allows_localhost(self):
        p = OllamaProvider(name="ollama", model_id="qwen2.5:3b")
        url = p.base_url.rstrip("/") + "/chat/completions"
        p.validate_target(url, resolve=False)  # 不应抛异常

    def test_ollama_allows_127(self):
        p = OllamaProvider(name="ollama", base_url="http://127.0.0.1:11434/v1",
                           model_id="qwen2.5:3b")
        p.validate_target(p.base_url + "/chat/completions", resolve=False)

    def test_ollama_still_blocks_private_range(self):
        # Ollama 放行 loopback，但 10.0.0.0/8 等私网仍拦截
        p = OllamaProvider(name="ollama", base_url="http://10.0.0.5:11434/v1",
                           model_id="qwen2.5:3b")
        with pytest.raises(ProviderError, match="目标地址不安全"):
            p.validate_target(p.base_url + "/chat/completions", resolve=False)

    def test_generic_blocks_localhost(self):
        p = OpenAICompatibleProvider(name="x", base_url="http://localhost:8080/v1", model_id="m")
        with pytest.raises(ProviderError, match="目标地址不安全"):
            p.validate_target(p.base_url + "/chat/completions", resolve=False)

    def test_generic_blocks_private_ip(self):
        p = OpenAICompatibleProvider(name="x", base_url="http://192.168.1.10/v1", model_id="m")
        with pytest.raises(ProviderError, match="目标地址不安全"):
            p.validate_target(p.base_url + "/chat/completions", resolve=False)

    def test_generic_allows_public(self):
        p = OpenAICompatibleProvider(name="x", base_url="https://api.example.com/v1", model_id="m")
        p.validate_target(p.base_url + "/chat/completions", resolve=False)  # 不抛

    def test_provider_from_config_validates(self):
        # 保存通用 Provider 到内网地址应被拒绝
        with pytest.raises(ProviderError, match="目标地址不安全"):
            providers.provider_from_config(
                {"provider_type": "openai_compatible", "base_url": "http://10.0.0.1/v1",
                 "model_id": "m"}, validate=True,
            )
        # Ollama localhost 通过
        p = providers.provider_from_config(
            {"provider_type": "ollama", "base_url": "http://localhost:11434/v1",
             "model_id": "qwen2.5:3b"}, validate=True,
        )
        assert isinstance(p, OllamaProvider)

    def test_build_request_resolves_dns_rebinding(self, monkeypatch):
        """通用 Provider 请求前 resolve=True：DNS 解析到内网应拒绝。"""
        monkeypatch.setattr(
            "app.connectors.ssrf.socket.getaddrinfo",
            lambda host, port=None: [(2, 1, 6, "", ("169.254.169.254", 0))],
        )
        p = OpenAICompatibleProvider(name="x", base_url="http://evil.example.com/v1", model_id="m")
        with pytest.raises(ProviderError, match="目标地址不安全"):
            p.build_request([{"role": "user", "content": "hi"}], stream=False)

    def test_ollama_build_request_ok(self):
        p = OllamaProvider(name="ollama", model_id="qwen2.5:3b")
        url, headers, body = p.build_request([{"role": "user", "content": "hi"}], stream=False)
        assert url.startswith("http://localhost:11434")


class TestApiKeyRefValidation:
    """api_key 输入分类：占位符 / 明文（走 .env 落地）/ 畸形占位符拒绝。"""

    def test_placeholder_ok(self):
        assert providers.classify_api_key_ref("{DEEPSEEK_API_KEY}") == "placeholder"
        providers.validate_api_key_ref("{DEEPSEEK_API_KEY}")  # 兼容入口不抛

    def test_empty_ok(self):
        assert providers.classify_api_key_ref(None) is None
        assert providers.classify_api_key_ref("") is None
        providers.validate_api_key_ref(None)  # 无 key 的 provider（如 Ollama）通过

    def test_plaintext_classified(self):
        # 明文不再"直接拒绝"：识别为 plaintext，由上层走 .env 落地路径
        assert providers.classify_api_key_ref("sk-abcdef123456") == "plaintext"
        assert providers.classify_api_key_ref("DEEPSEEK_API_KEY") == "plaintext"

    def test_malformed_placeholder_rejected(self):
        with pytest.raises(ProviderError, match="占位符"):
            providers.classify_api_key_ref("{DEEPSEEK_API_KEY")  # 只开头括号
        with pytest.raises(ProviderError, match="占位符"):
            providers.validate_api_key_ref("DEEPSEEK_API_KEY}")  # 只结尾括号


class TestSecretToEnv:
    """真实 key 直接填 → 写入 .env + 返回占位符引用（不落库明文）。"""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        yield
        for k in list(os.environ):
            if k.startswith("TSUMUGI_API_KEY_"):
                monkeypatch.delenv(k, raising=False)

    def _tmp_env(self, monkeypatch, tmp_path, initial=""):
        env_file = tmp_path / ".env"
        if initial:
            env_file.write_text(initial, encoding="utf-8")
        monkeypatch.setattr(providers, "SECRET_ENV_PATH", env_file)
        return env_file

    def test_persist_writes_env_and_returns_placeholder(self, monkeypatch, tmp_path):
        env_file = self._tmp_env(monkeypatch, tmp_path)
        ref = providers.persist_api_key_placeholder("deepseek", "sk-secret123")
        assert ref == "{TSUMUGI_API_KEY_DEEPSEEK}"
        content = env_file.read_text(encoding="utf-8")
        assert "TSUMUGI_API_KEY_DEEPSEEK=sk-secret123" in content
        # 运行时立即可解析
        assert providers._resolve_env_placeholder(ref) == "sk-secret123"

    def test_persist_replaces_existing_var(self, monkeypatch, tmp_path):
        env_file = self._tmp_env(monkeypatch, tmp_path, "TSUMUGI_API_KEY_DEEPSEEK=old\nDEEPSEEK_API_KEY=keep\n")
        providers.persist_api_key_placeholder("deepseek", "newkey")
        content = env_file.read_text(encoding="utf-8")
        assert "TSUMUGI_API_KEY_DEEPSEEK=newkey" in content
        assert "TSUMUGI_API_KEY_DEEPSEEK=old" not in content
        assert "DEEPSEEK_API_KEY=keep" in content  # 其它行保留

    def test_persist_different_providers_independent(self, monkeypatch, tmp_path):
        env_file = self._tmp_env(monkeypatch, tmp_path)
        r1 = providers.persist_api_key_placeholder("deepseek", "keyA")
        r2 = providers.persist_api_key_placeholder("ollama_custom", "keyB")
        assert r1 == "{TSUMUGI_API_KEY_DEEPSEEK}"
        assert r2 == "{TSUMUGI_API_KEY_OLLAMA_CUSTOM}"
        assert providers._resolve_env_placeholder(r1) == "keyA"
        assert providers._resolve_env_placeholder(r2) == "keyB"

    def test_write_quotes_value_with_spaces(self, monkeypatch, tmp_path):
        env_file = self._tmp_env(monkeypatch, tmp_path)
        providers.persist_api_key_placeholder("x", "key with spaces")
        content = env_file.read_text(encoding="utf-8")
        assert 'TSUMUGI_API_KEY_X="key with spaces"' in content

    def test_restart_reloads_from_env_file(self, monkeypatch, tmp_path):
        # 模拟"后端重启"：写入后清掉当前进程 env，再像 main.py 那样 load_dotenv
        env_file = self._tmp_env(monkeypatch, tmp_path)
        ref = providers.persist_api_key_placeholder("deepseek", "sk-persist")
        os.environ.pop("TSUMUGI_API_KEY_DEEPSEEK", None)
        assert providers._resolve_env_placeholder(ref) is None  # 当前进程 env 已清
        from dotenv import load_dotenv
        load_dotenv(str(env_file), override=True)
        assert providers._resolve_env_placeholder(ref) == "sk-persist"


class TestRagDegradation:
    async def test_rag_disabled_when_no_provider(self, monkeypatch):
        """未配置 provider 时 generate_answer 抛 AIAnswerDisabled（可选项提示）。"""
        monkeypatch.setattr(
            "app.rag._active_provider",
            lambda: (_ for _ in ()).throw(rag.AIAnswerDisabled("AI 问答未启用")),
        )
        from app.schemas import RetrievedChunk
        c = [RetrievedChunk(content="x", item_title="t", item_id=1, score=0.9)]
        with pytest.raises(rag.AIAnswerDisabled):
            await rag.generate_answer_non_stream("q", c)

    def test_model_table_exists(self, db):
        # 建表确认（conftest create_all 已含 LLMProviderConfig）
        assert "llm_providers" in LLMProviderConfig.__table__.name
