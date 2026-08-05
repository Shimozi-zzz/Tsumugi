"""RAG 模块 - prompt 拼接 + DeepSeek API 调用（手写，不使用 LangChain）

设计取舍详见 docs/decisions/0003-prompt-and-truncation.md。
"""
import json
from typing import AsyncGenerator, List, Optional

import httpx

from app.config import settings
from app.schemas import RetrievedChunk


class LLMError(Exception):
    """LLM API 调用失败（鉴权/限流/超时/网络错误等），message 可直接展示给用户。"""


SYSTEM_PROMPT_TEMPLATE = """你是一个严谨的个人知识库助手。请严格基于下面提供的"参考资料"回答用户问题。

要求：
1. 只依据参考资料作答；参考资料不足以回答时，明确说明"资料中没有相关信息"，不要编造。
2. 引用具体内容时标注来源标题，如（来源：《标题》）。
3. 回答使用中文，简洁、有条理。"""


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
        block = f"[{i}] 来源：{chunk.item_title or '未知来源'}\n{chunk.content}"
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


# ---------------------------------------------------------------- DeepSeek API

_PLACEHOLDER_KEY = "your_deepseek_api_key_here"


def _ensure_key() -> None:
    key = settings.deepseek_api_key.get_secret_value()
    if not key or key == _PLACEHOLDER_KEY:
        raise LLMError(
            "未配置 DEEPSEEK_API_KEY（当前为空或仍为占位符）。请在 .env 中填入真实 "
            "DeepSeek API Key 后重启后端。"
        )


def _chat_url() -> str:
    return settings.deepseek_api_base.rstrip("/") + "/chat/completions"


def _chat_body(messages: List[dict], stream: bool) -> dict:
    return {
        "model": settings.deepseek_model,
        "messages": messages,
        "stream": stream,
        "temperature": 0.2,
        "max_tokens": 2048,
    }


def _chat_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.deepseek_api_key.get_secret_value()}",
        "Content-Type": "application/json",
    }


def _map_http_error(exc: httpx.HTTPStatusError) -> LLMError:
    code = exc.response.status_code
    if code in (401, 403):
        return LLMError("DeepSeek API 鉴权失败，请检查 DEEPSEEK_API_KEY 是否正确。")
    if code == 429:
        return LLMError("DeepSeek API 请求过于频繁（限流），请稍后再试。")
    if code == 400:
        return LLMError(f"DeepSeek API 请求参数错误：{exc.response.text[:200]}")
    return LLMError(f"DeepSeek API 返回错误状态码 {code}。")


async def _chat_once(messages: List[dict], stream: bool):
    """发起一次请求，返回 (client, response)。stream 请求返回未消费的流式响应。"""
    _ensure_key()
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.llm_timeout, connect=10.0)
    )
    try:
        if stream:
            request = client.build_request(
                "POST", _chat_url(), headers=_chat_headers(), json=_chat_body(messages, True)
            )
            response = await client.send(request, stream=True)
            if response.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"LLM 请求失败 {response.status_code}",
                    request=request,
                    response=response,
                )
            return client, response
        else:
            response = await client.post(
                _chat_url(), headers=_chat_headers(), json=_chat_body(messages, False)
            )
            response.raise_for_status()
            await client.aclose()
            return None, response
    except Exception:
        await client.aclose()
        raise


async def _chat(messages: List[dict]) -> str:
    """非流式调用，返回完整回答。对超时/网络错误做有限重试。"""
    last_exc: Optional[Exception] = None
    for attempt in range(settings.llm_max_retries + 1):
        try:
            _, response = await _chat_once(messages, stream=False)
            payload = response.json()
            content = payload["choices"][0]["message"].get("content") or ""
            return content
        except httpx.HTTPStatusError as exc:
            raise _map_http_error(exc) from exc
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
    for attempt in range(settings.llm_max_retries + 1):
        client = None
        response = None
        try:
            client, response = await _chat_once(messages, stream=True)
        except httpx.HTTPStatusError as exc:
            raise _map_http_error(exc) from exc
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
            raise _map_http_error(exc) from exc
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
