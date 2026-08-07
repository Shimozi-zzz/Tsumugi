"""LLM Provider 抽象层

设计（详见 docs/decisions/0013-llm-provider-architecture.md）：
- 只负责"给定 messages，如何向后端发请求"——返回 (url, headers, body)，
  让 rag.py 保留已验证的流式解析/超时/重试/错误映射逻辑不动；
- 统一走 OpenAI 兼容的 `chat.completions` 接口（不用 Responses API，
  部分网关不支持 Responses）；
- DeepSeek = OpenAICompatibleProvider 的一个预设；Ollama 用它自带的
  OpenAI 兼容端点（/v1），无需 api_key。
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional, Protocol, runtime_checkable

import httpx

from app.connectors.ssrf import SSRFError, check_ssrf_target


class ProviderError(Exception):
    """Provider 配置/请求错误，message 可展示给用户。"""


@runtime_checkable
class LLMProvider(Protocol):
    """统一 LLM Provider 接口。"""

    name: str
    provider_type: str  # "openai_compatible" | "ollama"
    base_url: str
    api_key: Optional[str]
    model_id: str

    def build_request(
        self, messages: List[dict], stream: bool
    ) -> tuple[str, Dict[str, str], Dict]:
        """构造 (url, headers, body)。stream 请求用流式字段。"""


def _chat_body(model_id: str, messages: List[dict], stream: bool) -> Dict:
    return {
        "model": model_id,
        "messages": messages,
        "stream": stream,
        "temperature": 0.2,
        "max_tokens": 2048,
    }


def _headers(api_key: Optional[str]) -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    return h


@dataclass
class OpenAICompatibleProvider:
    """通用 OpenAI 兼容 Provider（走 chat.completions）。

    - base_url：API 根地址（如 https://api.deepseek.com/v1），会自动拼
      /chat/completions；
    - api_key：可空（部分兼容服务无需 key）；
    - model_id：模型名（如 deepseek-chat / qwen2.5:7b）。
    """

    name: str
    provider_type: str = "openai_compatible"
    base_url: str = ""
    api_key: Optional[str] = None
    model_id: str = ""

    def __post_init__(self):
        if not self.base_url or not self.model_id:
            raise ProviderError("openai_compatible Provider 需要 base_url 和 model_id")

    def validate_target(self, url: str, resolve: bool = True) -> None:
        """通用 Provider 与 Connector 同风险：完整 SSRF 校验（不放宽）。"""
        try:
            check_ssrf_target(url, resolve=resolve, allow_loopback=False)
        except SSRFError as e:
            raise ProviderError(f"目标地址不安全：{e}") from e

    def build_request(
        self, messages: List[dict], stream: bool
    ) -> tuple[str, Dict[str, str], Dict]:
        url = self.base_url.rstrip("/") + "/chat/completions"
        self.validate_target(url, resolve=True)  # 请求前完整校验（含 DNS rebinding）
        return url, _headers(self.api_key), _chat_body(self.model_id, messages, stream)


@dataclass
class OllamaProvider:
    """Ollama 本地 Provider（使用其自带 OpenAI 兼容端点 /v1）。

    - base_url 默认 http://localhost:11434/v1，无需 api_key；
    - model_id 由用户在本地已拉取模型中选择。
    """

    name: str
    provider_type: str = "ollama"
    base_url: str = "http://localhost:11434/v1"
    api_key: Optional[str] = None
    model_id: str = ""

    def __post_init__(self):
        if not self.model_id:
            raise ProviderError("Ollama Provider 需要 model_id")

    def validate_target(self, url: str, resolve: bool = True) -> None:
        """Ollama 是本机预期服务：放行回环地址，但其它私网/链路本地仍拦截。"""
        try:
            check_ssrf_target(url, resolve=resolve, allow_loopback=True)
        except SSRFError as e:
            raise ProviderError(f"目标地址不安全：{e}") from e

    def build_request(
        self, messages: List[dict], stream: bool
    ) -> tuple[str, Dict[str, str], Dict]:
        url = self.base_url.rstrip("/") + "/chat/completions"
        self.validate_target(url, resolve=True)
        return url, _headers(self.api_key), _chat_body(self.model_id, messages, stream)


def provider_from_config(config: dict, validate: bool = True) -> LLMProvider:
    """从持久化配置 dict 构造 Provider 实例。

    validate=True 时做配置期 SSRF 校验（resolve=False，协议 + IP 字面量 +
    localhost；Ollama 放行回环）。保存配置时调用方应传 validate=True，
    请求时才做 resolve=True 的完整校验。
    """
    ptype = config.get("provider_type", "openai_compatible")
    kwargs = {
        "name": config.get("name", "default"),
        "base_url": config.get("base_url", ""),
        # api_key 支持环境变量占位符（如 {OPENAI_API_KEY}），运行时解析
        "api_key": _resolve_env_placeholder(config.get("api_key_ref"))
                   or config.get("api_key"),
        "model_id": config.get("model_id", ""),
    }
    if ptype == "ollama":
        provider = OllamaProvider(**kwargs)
    else:
        provider = OpenAICompatibleProvider(**kwargs)
    if validate:
        # 配置期轻校验（resolve=False，不做 DNS 解析）
        url = provider.base_url.rstrip("/") + "/chat/completions"
        provider.validate_target(url, resolve=False)
    return provider


def _resolve_env_placeholder(ref: Optional[str]) -> Optional[str]:
    """把环境变量占位符（如 {MY_KEY}）解析为环境变量值；非占位符原样返回。"""
    if not ref:
        return None
    ref = str(ref).strip()
    if ref.startswith("{") and ref.endswith("}"):
        return os.environ.get(ref[1:-1]) or None
    return ref or None


# .env 写入路径（模块级常量，测试可 monkeypatch 到临时目录，避免污染真实 .env）
SECRET_ENV_PATH = Path(".env")


def is_env_placeholder(ref: Optional[str]) -> bool:
    """是否 {ENV_VAR} 占位符格式。"""
    if not ref:
        return False
    value = str(ref).strip()
    return value.startswith("{") and value.endswith("}") and len(value) > 2


def classify_api_key_ref(ref: Optional[str]) -> Optional[str]:
    """区分 api_key 输入类型，决定处理路径（UI 填 key 体验，见 ADR 0017）：
    - None / 空 → None（无需 key 的 provider，如 Ollama）；
    - "{ENV_VAR}" → "placeholder"（存占位符引用）；
    - 其它非空 → "plaintext"（真实 key，由调用方走"写入 .env"落地路径，
      不落数据库明文）。
    畸形占位符（只有一边括号）抛 ProviderError。
    """
    if ref is None or not str(ref).strip():
        return None
    value = str(ref).strip()
    if is_env_placeholder(value):
        return "placeholder"
    if value.startswith("{") or value.endswith("}"):
        raise ProviderError("API Key 占位符格式不完整：应为 {ENV_VAR}")
    return "plaintext"


def validate_api_key_ref(ref: Optional[str]) -> None:
    """兼容入口：调用 classify 校验格式（畸形占位符抛错；空值/明文通过——
    明文由上层走 .env 落地路径，不再是"直接拒绝"）。"""
    classify_api_key_ref(ref)


def api_key_env_var_name(provider_name: str) -> str:
    """由 provider 名生成 .env 变量名：TSUMUGI_API_KEY_{NAME}（大写、字母数字下划线）。"""
    sanitized = "".join(c for c in str(provider_name).upper() if c.isalnum() or c == "_")
    return f"TSUMUGI_API_KEY_{sanitized or 'PROVIDER'}"


def write_secret_to_env(var_name: str, value: str) -> str:
    """把真实密钥写入 .env（UTF-8，保留其它行，已 gitignore），并同步 os.environ。

    返回变量名。值含空格/#/引号时用双引号包裹（dotenv 语法）。
    """
    var_name = var_name.upper()
    raw = str(value).strip()
    env_path = Path(SECRET_ENV_PATH)
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    if any(ch in raw for ch in " #\"") or "=" in raw:
        entry = f'{var_name}="{raw.replace(chr(34), chr(92) + chr(34))}"'
    else:
        entry = f"{var_name}={raw}"

    prefix = f"{var_name}="
    found = False
    new_lines = []
    for ln in lines:
        if ln.strip().startswith(prefix):
            new_lines.append(entry)
            found = True
        else:
            new_lines.append(ln)
    if not found:
        new_lines.append(entry)
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # 立即生效：同步 os.environ（当前进程）并从文件刷新（防手改遗漏）
    os.environ[var_name] = raw
    try:
        from dotenv import load_dotenv
        load_dotenv(str(env_path), override=False)
    except ImportError:
        pass
    return var_name


def persist_api_key_placeholder(provider_name: str, plaintext: str) -> str:
    """把用户直接填的真实 key 写入 .env，返回占位符引用 {VAR} 供存库（不落明文）。"""
    var_name = api_key_env_var_name(provider_name)
    write_secret_to_env(var_name, plaintext)
    return "{" + var_name + "}"


# ---- 预设 ----

DEEPSEEK_PRESET = {
    "name": "deepseek",
    "display_name": "DeepSeek",
    "provider_type": "openai_compatible",
    "base_url": "https://api.deepseek.com/v1",
    "api_key_ref": "{DEEPSEEK_API_KEY}",
    "model_id": "deepseek-chat",
}

OLLAMA_PRESET = {
    "name": "ollama",
    "display_name": "Ollama 本地",
    "provider_type": "ollama",
    "base_url": "http://localhost:11434/v1",
    "model_id": "qwen2.5:3b",
}

# 推荐的中文友好轻量模型（Ollama 引导教程用）
OLLAMA_RECOMMENDED_MODELS = [
    {"tag": "qwen2.5:3b", "note": "Qwen 2.5 3B，中文效果好、体积适中（约 2GB），普通电脑可跑"},
    {"tag": "qwen2.5:7b", "note": "Qwen 2.5 7B，中文更强但更吃内存（约 5GB）"},
]


def test_connection(config: dict, timeout: float = 10.0) -> str:
    """极简测试请求：发一条 "ping" 消息，验证 provider 配置可用。

    返回成功提示或抛 ProviderError（含具体原因）。
    """
    provider = provider_from_config(config)
    url, headers, body = provider.build_request(
        [{"role": "user", "content": "ping"}], stream=False,
    )
    # 最小化请求，避免触发内容审核等
    body["max_tokens"] = 5
    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise ProviderError(f"连接失败（HTTP {e.response.status_code}）：{e.response.text[:200]}") from e
    except httpx.ConnectError as e:
        raise ProviderError(f"连接失败（无法连接 {url}）：{e}") from e
    except httpx.TimeoutException as e:
        raise ProviderError(f"连接失败（请求超时）：{e}") from e
    except httpx.HTTPError as e:
        raise ProviderError(f"连接失败：{e}") from e
    return f"连接成功（{provider.name} / {provider.model_id}）"
