"""S3-5 LLM 流式适配器：httpx.MockTransport，禁止真实网络。"""
from __future__ import annotations

import json

import httpx
import pytest

from app.ai.llm import (
    LLMClient,
    LLMError,
    LLMMessage,
    LLMResponse,
    LLMStreamChunk,
    OpenAICompatibleLLMClient,
)


def _sse(*chunks: dict) -> bytes:
    return b"".join(
        f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
        for chunk in chunks
    ) + b"data: [DONE]\n\n"


def _client(handler, **kwargs) -> OpenAICompatibleLLMClient:
    return OpenAICompatibleLLMClient(
        api_key="sk-test-llm",
        base_url="https://example.test/v1",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        **kwargs,
    )


class FakeChatOnly(LLMClient):
    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
        return LLMResponse(
            text="完整回答",
            model="fake",
            prompt_tokens=10,
            completion_tokens=4,
            total_tokens=14,
            latency_ms=3,
            cost_yuan=0.00001,
        )


def test_chat_stream_default_falls_back_to_one_chunk() -> None:
    chunks = list(FakeChatOnly(model="fake").chat_stream([LLMMessage("user", "问")]))

    assert chunks[0].text == "完整回答"
    assert chunks[0].response is None
    assert chunks[1].text == ""
    assert chunks[1].response is not None
    assert chunks[1].response.total_tokens == 14


def test_chat_stream_parses_deltas_and_usage() -> None:
    body = _sse(
        {"choices": [{"delta": {"content": "答"}}]},
        {"choices": [{"delta": {"content": "[1]"}}]},
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        },
    )
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=body)

    chunks = list(
        _client(handler).chat_stream(
            [LLMMessage("user", "问题")], temperature=0.1, max_tokens=200
        )
    )

    assert "".join(chunk.text for chunk in chunks) == "答[1]"
    final = chunks[-1].response
    assert final is not None
    assert final.model == "qwen-plus"
    assert final.prompt_tokens == 100
    assert final.completion_tokens == 20
    assert final.total_tokens == 120
    assert final.cost_yuan == pytest.approx(0.00012)
    payload = json.loads(captured[0].content)
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["temperature"] == 0.1
    assert payload["max_tokens"] == 200


def test_chat_stream_estimates_usage_when_missing() -> None:
    body = _sse({"choices": [{"delta": {"content": "没有 usage"}}]})
    chunks = list(
        _client(lambda request: httpx.Response(200, content=body)).chat_stream(
            [LLMMessage("user", "问题")]
        )
    )

    final = chunks[-1].response
    assert final is not None
    assert final.prompt_tokens > 0
    assert final.completion_tokens > 0
    assert final.total_tokens == final.prompt_tokens + final.completion_tokens
    assert final.cost_yuan > 0


def test_chat_stream_retries_500_before_first_delta() -> None:
    calls = 0
    body = _sse({"choices": [{"delta": {"content": "答"}}]})

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, json={"error": "temporary"})
        return httpx.Response(200, content=body)

    chunks = list(_client(handler).chat_stream([LLMMessage("user", "问题")]))

    assert calls == 2
    assert "".join(chunk.text for chunk in chunks) == "答"


def test_chat_stream_does_not_retry_after_delta() -> None:
    calls = 0
    body = (
        b'data: {"choices":[{"delta":{"content":"\xe7\xad\x94"}}]}\n\n'
        b"data: {broken-json}\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=body)

    stream = _client(handler).chat_stream([LLMMessage("user", "问题")])
    assert next(stream).text == "答"
    with pytest.raises(LLMError):
        next(stream)
    assert calls == 1