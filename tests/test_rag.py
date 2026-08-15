"""rag 模块测试：prompt 拼接、截断、流式/非流式调用（mock HTTP）、错误处理"""
import json

import httpx
import pytest
from pydantic import SecretStr

import app.rag as rag
from app.rag import (
    LLMError,
    build_context_prompt,
    build_messages,
    build_system_prompt,
    generate_answer,
    generate_answer_non_stream,
)
from app.schemas import RetrievedChunk


def chunk(content, item_title="标题", item_id=1, score=0.9):
    return RetrievedChunk(content=content, item_title=item_title, item_id=item_id, score=score)


# ---------------------------------------------------------------- prompt

class TestPrompt:
    def test_system_prompt_mentions_sources(self):
        prompt = build_system_prompt()
        assert "参考资料" in prompt
        assert "不要编造" in prompt or "不编造" in prompt

    def test_system_prompt_defines_personal_record_sources(self):
        """Phase 10-1-B-1：个人来源统一定义为 我的记忆/我的书评/我的笔记。"""
        prompt = build_system_prompt()
        assert "我的记忆" in prompt
        assert "我的书评" in prompt
        assert "我的笔记" in prompt
        assert "百科资料" in prompt

    def test_system_prompt_prioritizes_personal_records(self):
        """Phase 10-1-B-1：个人相关问题优先参考 我的记忆→我的书评→我的笔记。"""
        prompt = build_system_prompt()
        for keyword in ["我为什么喜欢", "和我的关系", "我的经历", "去年", "想重温", "推荐我"]:
            assert keyword in prompt
        # 优先级顺序与"没有找到个人记录"回退
        assert prompt.index("我的记忆") < prompt.index("我的书评") < prompt.index("我的笔记")
        assert "没有找到你关于这一点的个人记录" in prompt

    def test_system_prompt_distinguishes_sources_in_answer(self):
        """Phase 10-1-B-1：回答区分『你的记录中……』与『资料显示……』。"""
        prompt = build_system_prompt()
        assert "你的记录中" in prompt
        assert "资料显示" in prompt

    def test_context_prompt_labels_memory_review_external(self):
        """Phase 10-1-B-1 回归：build_context_prompt 的来源标签不变化（我的记忆/我的书评/百科资料）。"""
        from app.rag import build_context_prompt as bcp
        from app.schemas import RetrievedChunk as RC

        def mk(source_type, **kw):
            base = dict(content="片段", item_title="标题", item_id=1, score=0.9, source_type=source_type)
            base.update(kw)
            return RC(**base)

        text = bcp([
            mk("memory"),
            mk("review", review_title="无题"),
            mk("external_reference", connector="bangumi"),
        ], max_context_length=10000)
        assert "我的记忆" in text
        assert "我的书评" in text
        assert "百科资料" in text

    def test_context_prompt_format(self):
        chunks = [chunk("内容一", item_title="文档A"), chunk("内容二", item_title="文档B")]
        text = build_context_prompt(chunks, max_context_length=10000)
        assert "来源：文档A" in text
        assert "内容一" in text
        assert "来源：文档B" in text
        assert "内容二" in text

    def test_context_prompt_truncates_by_total_length(self):
        chunks = [chunk("长" * 300, item_title="A"), chunk("长" * 300, item_title="B")]
        text = build_context_prompt(chunks, max_context_length=350)
        # 预算不足时：第一条完整、第二条保留但被截断并标记
        assert "来源：A" in text
        assert "来源：B" in text
        assert "截断" in text
        assert len(text) < 500  # 总长控制在预算 + 头部/标记的余量内

    def test_context_prompt_empty(self):
        assert "无可用资料" in build_context_prompt([])

    def test_build_messages(self):
        messages = build_messages("什么是RAG？", [chunk("上下文内容")], max_context_length=5000)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "什么是RAG？" in messages[1]["content"]
        assert "上下文内容" in messages[1]["content"]


# ---------------------------------------------------------------- mock HTTP

class FakeStreamResponse:
    status_code = 200

    def __init__(self, lines, status_code=200):
        self._lines = lines
        self.status_code = status_code

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class FakeAsyncClient:
    """可配置行为的假 httpx.AsyncClient。behavior: ok | error | timeout"""

    def __init__(self, behavior="ok", lines=None, status_code=200, non_stream_payload=None):
        self.behavior = behavior
        self.lines = lines or []
        self.status_code = status_code
        self.non_stream_payload = non_stream_payload
        self.last_json = None

    def build_request(self, method, url, headers=None, json=None):
        self.last_json = json
        return httpx.Request(method, url)

    async def send(self, request, stream=False):
        if self.behavior == "error":
            return httpx.Response(self.status_code, request=request, text="boom")
        return FakeStreamResponse(self.lines)

    async def post(self, url, headers=None, json=None):
        self.last_json = json
        request = httpx.Request("POST", url)
        if self.behavior == "error":
            return httpx.Response(self.status_code, request=request, text="boom")
        if self.behavior == "timeout":
            raise httpx.TimeoutException("timeout", request=request)
        return httpx.Response(200, request=request, json=self.non_stream_payload or {
            "choices": [{"message": {"content": "完整答案"}}]
        })

    async def aclose(self):
        pass


@pytest.fixture(scope="function")
def fake_http(monkeypatch):
    # 注入一个启用的 provider（否则 _active_provider 查库报 AIAnswerDisabled）。
    # 用公网 IP 字面量 8.8.8.8：SSRF 放行且无需 DNS 解析。
    from app.providers import OpenAICompatibleProvider
    monkeypatch.setattr(
        rag, "_active_provider",
        lambda: OpenAICompatibleProvider(
            name="test", base_url="https://8.8.8.8/v1",
            api_key="test-key", model_id="test-model",
        ),
    )

    def install(client):
        monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
        return client

    return install


def sse_line(content=None, done=False):
    if done:
        return "data: [DONE]"
    return "data: " + json.dumps({"choices": [{"delta": {"content": content}}]}, ensure_ascii=False)


class TestGenerateAnswer:
    async def test_stream_yields_pieces(self, fake_http):
        client = FakeAsyncClient(lines=[sse_line("你好"), sse_line("，世界"), sse_line(done=True)])
        fake_http(client)
        pieces = [p async for p in generate_answer("问题", [chunk("内容")], stream=True)]
        assert "".join(pieces) == "你好，世界"
        assert client.last_json["stream"] is True

    async def test_stream_ignores_garbage_lines(self, fake_http):
        client = FakeAsyncClient(lines=[
            ":", "data: not-json", sse_line("有效"), "data: [DONE]",
        ])
        fake_http(client)
        pieces = [p async for p in generate_answer("问题", [chunk("内容")], stream=True)]
        assert pieces == ["有效"]

    async def test_non_stream_returns_full_answer(self, fake_http):
        fake_http(FakeAsyncClient())
        answer = await generate_answer_non_stream("问题", [chunk("内容")])
        assert answer == "完整答案"

    async def test_stream_auth_error(self, fake_http):
        fake_http(FakeAsyncClient(behavior="error", status_code=401))
        with pytest.raises(LLMError) as exc:
            [p async for p in generate_answer("问题", [chunk("内容")], stream=True)]
        assert "鉴权" in str(exc.value)

    async def test_non_stream_rate_limit(self, fake_http):
        fake_http(FakeAsyncClient(behavior="error", status_code=429))
        with pytest.raises(LLMError) as exc:
            await generate_answer_non_stream("问题", [chunk("内容")])
        assert "限流" in str(exc.value)

    async def test_timeout_retries_then_errors(self, fake_http, monkeypatch):
        fake_http(FakeAsyncClient(behavior="timeout"))
        monkeypatch.setattr(rag.settings, "llm_max_retries", 2)
        with pytest.raises(LLMError) as exc:
            await generate_answer_non_stream("问题", [chunk("内容")])
        assert "重试" in str(exc.value) or "失败" in str(exc.value)

    async def test_no_provider_raises_ai_disabled(self, monkeypatch):
        """未配置任何 provider 时抛 AIAnswerDisabled（可选项提示而非故障）。"""
        monkeypatch.setattr(
            "app.rag._active_provider",
            lambda: (_ for _ in ()).throw(rag.AIAnswerDisabled("AI 问答未启用")),
        )
        with pytest.raises(rag.AIAnswerDisabled) as exc:
            await generate_answer_non_stream("问题", [chunk("内容")])
        assert "未启用" in str(exc.value)

    async def test_messages_sent_correctly(self, fake_http):
        client = FakeAsyncClient(lines=[sse_line("好的")])
        fake_http(client)
        [p async for p in generate_answer("什么是向量检索？", [chunk("上下文")], stream=True)]
        messages = client.last_json["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "什么是向量检索？" in messages[1]["content"]
