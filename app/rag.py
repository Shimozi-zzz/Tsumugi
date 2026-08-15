"""RAG 模块 - prompt 拼接 + LLM Provider 调用（手写，不使用 LangChain）

设计取舍详见 docs/decisions/0003-prompt-and-truncation.md。
LLM Provider 可插拔化见 docs/decisions/0013-llm-provider-architecture.md。
"""
import json
from typing import AsyncGenerator, List, Optional

import httpx

from app.config import settings
from app.schemas import RetrievedChunk


class LLMError(Exception):
    """LLM API 调用失败（鉴权/限流/超时/网络错误等），message 可直接展示给用户。"""


class AIAnswerDisabled(LLMError):
    """AI 问答未启用/未配置 provider——非故障，是可选项提示。"""


SYSTEM_PROMPT_TEMPLATE = """你是一个严谨的个人知识库助手。请严格基于下面提供的"参考资料"回答用户问题。

参考资料包含两类来源，请始终区分、不要混为一谈：
- 用户自己的记录（个人经历）：我的记忆、我的书评（读后感）、我的笔记（标注为"我的记忆"/"我的书评"/"我的笔记"）；
- 作品资料与外部百科资料：作品简介、角色小传等（标注为"百科资料"）。

要求：
1. 只依据参考资料作答；参考资料不足以回答时，明确说明"资料中没有相关信息"，不要编造。
2. 引用具体内容时标注来源标题与类型，如（来源：《标题》，我的书评）/（来源：《标题》，百科资料）。
3. 个人相关的问题——如"我为什么喜欢""这部作品和我的关系""我的经历/回忆""去年/以前""想重温""推荐我"——
   应优先参考用户的个人记录，优先级为：我的记忆 → 我的书评 → 我的笔记；作品资料与外部百科资料只作
   事实补充，不能取代个人经历。如果参考资料中没有找到相应的个人记录，明确说明"没有找到你关于这一点的个人记录"，
   不要编造或臆测个人经历。
4. 回答时要区分个人经历与作品资料：引用个人记录时使用"你的记录中……"，引用作品资料时使用
   "资料显示……"，不要混淆两者。
5. 回答使用中文，简洁、有条理。"""


# ---------------------------------------------------------------- Provider 解析

def get_active_provider_config() -> Optional[dict]:
    """返回当前启用的 provider 配置；无则 None。"""
    from app import provider_store
    return provider_store.get_enabled_provider()


def _active_provider():
    """构造当前启用的 Provider 实例；未启用抛 AIAnswerDisabled。"""
    from app import provider_store, providers

    config = provider_store.get_enabled_provider()
    if config is None:
        raise AIAnswerDisabled(
            "AI 问答未启用：未配置任何可用的模型 Provider。"
            "请在「设置 → 模型 Provider」中启用一个（支持 DeepSeek / Ollama 本地）。"
        )
    try:
        return providers.provider_from_config(config)
    except providers.ProviderError as e:
        raise AIAnswerDisabled(f"AI 问答未启用：{e}") from e


# ---------------------------------------------------------------- prompt 拼接

def build_system_prompt() -> str:
    """构建 system prompt。"""
    return SYSTEM_PROMPT_TEMPLATE


def build_context_prompt(
    chunks: List[RetrievedChunk],
    max_context_length: Optional[int] = None,
) -> str:
    """把检索结果格式化为参考上下文字符串，按累计字符数截断。

    chunks 已按相关度降序排列，越靠前越重要，因此"按顺序截断、只保留前缀"
    能最大化保留最有用的信息。单个 chunk 超过剩余预算时在内部截断并标记。
    """
    max_context_length = max_context_length or settings.max_context_length
    parts: List[str] = []
    budget = max_context_length

    for i, chunk in enumerate(chunks, start=1):
        if budget <= 0:
            break
        # 来源标注：区分"用户自己写的"（note/review）与"外部下载的百科资料"
        source_label = chunk.item_title or "未知来源"
        if chunk.source_type == "review":
            source_label = f"{source_label}（我的书评：{chunk.review_title or '无题'}）"
        elif chunk.source_type == "external_reference":
            conn = chunk.connector or ""
            source_label = f"{source_label}（百科资料{f'：{conn}' if conn else ''}）"
        elif chunk.source_type == "note":
            source_label = f"{source_label}（我的笔记）"
        elif chunk.source_type == "memory":
            source_label = f"{source_label}（我的记忆）"
        block = f"[{i}] 来源：{source_label}\n{chunk.content}"
        if len(block) > budget:
            parts.append(block[:budget] + "\n…（此条已截断）")
            budget = 0
            break
        parts.append(block)
        budget -= len(block) + 2

    return "\n\n".join(parts) if parts else "（无可用资料）"


def build_messages(
    query: str,
    chunks: List[RetrievedChunk],
    max_context_length: Optional[int] = None,
) -> List[dict]:
    """构建 DeepSeek 的 messages 请求体。"""
    user_content = (
        "【参考资料】\n"
        f"{build_context_prompt(chunks, max_context_length)}\n\n"
        f"【用户问题】\n{query}"
    )
    return [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": user_content},
    ]


# ---------------------------------------------------------------- Provider 请求

def _build_provider_request(messages: List[dict], stream: bool):
    """从启用的 Provider 构造 (provider, url, headers, body)。"""
    provider = _active_provider()  # 可能抛 AIAnswerDisabled
    try:
        url, headers, body = provider.build_request(messages, stream)
    except Exception as e:
        raise LLMError(f"构造 {provider.name} 请求失败：{e}") from e
    return provider, url, headers, body


def _map_http_error(exc: httpx.HTTPStatusError, provider_name: str) -> LLMError:
    code = exc.response.status_code
    if code in (401, 403):
        return LLMError(f"{provider_name} 鉴权失败，请检查 API Key 配置是否正确。")
    if code == 429:
        return LLMError(f"{provider_name} 请求过于频繁（限流），请稍后再试。")
    if code == 400:
        return LLMError(f"{provider_name} 请求参数错误：{exc.response.text[:200]}")
    return LLMError(f"{provider_name} 返回错误状态码 {code}。")


async def _chat_once(messages: List[dict], stream: bool):
    """发起一次请求，返回 (client, response, provider_name)。stream 请求返回未消费的流式响应。"""
    provider, url, headers, body = _build_provider_request(messages, stream)
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.llm_timeout, connect=10.0)
    )
    try:
        if stream:
            request = client.build_request(
                "POST", url, headers=headers, json=body
            )
            response = await client.send(request, stream=True)
            if response.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"LLM 请求失败 {response.status_code}",
                    request=request,
                    response=response,
                )
            return client, response, provider.name
        else:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            await client.aclose()
            return None, response, provider.name
    except Exception:
        await client.aclose()
        raise


async def _chat(messages: List[dict]) -> str:
    """非流式调用，返回完整回答。对超时/网络错误做有限重试。"""
    last_exc: Optional[Exception] = None
    provider_name = "LLM"
    for attempt in range(settings.llm_max_retries + 1):
        try:
            _, response, provider_name = await _chat_once(messages, stream=False)
            payload = response.json()
            content = payload["choices"][0]["message"].get("content") or ""
            return content
        except httpx.HTTPStatusError as exc:
            raise _map_http_error(exc, provider_name) from exc
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as exc:
            last_exc = exc
            if attempt >= settings.llm_max_retries:
                raise LLMError(f"LLM 请求失败（已重试 {attempt} 次）：{exc}") from exc
    raise LLMError(f"LLM 请求失败：{last_exc}")


async def _stream_chat(messages: List[dict]) -> AsyncGenerator[str, None]:
    """流式调用，逐段 yield 回答文本；结束或出错时关闭连接。

    重试策略：仅当**尚未产出任何内容**时对网络错误重试（重发完整请求不会
    造成重复内容）；一旦已 yield 过片段，中途失败直接抛出（前端已收到部分
    内容，无法安全重连）。HTTP 状态错误不重试。
    """
    emitted = False
    provider_name = "LLM"
    for attempt in range(settings.llm_max_retries + 1):
        client = None
        response = None
        try:
            client, response, provider_name = await _chat_once(messages, stream=True)
        except httpx.HTTPStatusError as exc:
            raise _map_http_error(exc, provider_name) from exc
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as exc:
            if attempt >= settings.llm_max_retries:
                raise LLMError(f"LLM 流式请求失败（已重试 {attempt} 次）：{exc}") from exc
            continue  # 尚未产出内容，重试

        try:
            async for line in response.aiter_lines():
                line = (line or "").strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    return
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = payload.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta", {}).get("content")
                if delta:
                    emitted = True
                    yield delta
            return  # 正常结束
        except httpx.HTTPStatusError as exc:
            raise _map_http_error(exc, provider_name) from exc
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as exc:
            if emitted or attempt >= settings.llm_max_retries:
                raise LLMError(f"LLM 流式请求失败：{exc}") from exc
            continue  # 尚未产出内容，重试
        finally:
            await client.aclose()


async def generate_answer(
    query: str,
    retrieved_chunks: List[RetrievedChunk],
    stream: bool = True,
) -> AsyncGenerator[str, None]:
    """基于检索结果生成答案。stream=True 流式输出文本片段。"""
    messages = build_messages(query, retrieved_chunks)
    if stream:
        async for piece in _stream_chat(messages):
            yield piece
    else:
        yield await _chat(messages)


async def generate_answer_non_stream(
    query: str,
    retrieved_chunks: List[RetrievedChunk],
) -> str:
    """非流式版本：一次性返回完整答案。"""
    messages = build_messages(query, retrieved_chunks)
    return await _chat(messages)
