"""S1-6 LLM 适配器：全部用 httpx.MockTransport，禁止真实网络。"""
from __future__ import annotations

import json

import httpx
import pytest

from app.ai.llm import LLMError, LLMMessage, OpenAICompatibleLLMClient


def _ok(content: str = "答[1]", usage: dict | None = None) -> httpx.Response:
    payload = {
        "choices": [{"message": {"content": content}}],
        "usage": usage,
    }
    return httpx.Response(200, json=payload)


def _client(handler, **kwargs) -> OpenAICompatibleLLMClient:
    return OpenAICompatibleLLMClient(
        api_key="sk-test-llm",
        base_url="https://example.test/v1",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        **kwargs,
    )


def test_llm_chat_success_parses_usage_and_cost() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _ok(
            "结论[1]",
            {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        )

    client = _client(handler)
    response = client.chat(
        [LLMMessage("user", "问题")],
        temperature=0.1,
        max_tokens=200,
    )

    assert response.text == "结论[1]"
    assert response.model == "qwen-plus"
    assert response.prompt_tokens == 100
    assert response.completion_tokens == 20
    assert response.total_tokens == 120
    assert response.cost_yuan == pytest.approx(0.00012)
    assert len(captured) == 1
    req = captured[0]
    assert str(req.url) == "https://example.test/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer sk-test-llm"
    body = json.loads(req.content)
    assert body["model"] == "qwen-plus"
    assert body["messages"] == [{"role": "user", "content": "问题"}]
    assert body["temperature"] == 0.1
    assert body["max_tokens"] == 200


def test_llm_chat_retries_500_then_success() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, json={"error": "temporary"})
        return _ok()

    client = OpenAICompatibleLLMClient(
        api_key="sk-test-llm",
        base_url="https://example.test/v1",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    response = client.chat([LLMMessage("user", "问题")])

    assert response.text == "答[1]"
    assert calls == 2
    assert len(sleeps) == 1


def test_llm_chat_400_not_retried_and_does_not_leak_body() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            400,
            json={"error": {"message": "PROMPT_SECRET_SHOULD_NOT_LEAK"}},
        )

    client = _client(handler)
    with pytest.raises(LLMError) as exc_info:
        client.chat([LLMMessage("user", "问题")])

    assert calls == 1
    assert "HTTP 400" in str(exc_info.value)
    assert "PROMPT_SECRET_SHOULD_NOT_LEAK" not in str(exc_info.value)
    assert exc_info.value.retryable is False


def test_llm_chat_malformed_response_raises() -> None:
    client = _client(lambda request: httpx.Response(200, json={"choices": []}))
    with pytest.raises(LLMError):
        client.chat([LLMMessage("user", "问题")])


def test_llm_chat_missing_usage_defaults_zero() -> None:
    client = _client(lambda request: _ok("答[1]", None))
    response = client.chat([LLMMessage("user", "问题")])
    assert response.prompt_tokens == 0
    assert response.completion_tokens == 0
    assert response.total_tokens == 0
    assert response.cost_yuan == 0.0


def test_llm_missing_key_raises() -> None:
    with pytest.raises(LLMError):
        OpenAICompatibleLLMClient(
            api_key="",
            base_url="https://example.test/v1",
            transport=httpx.MockTransport(lambda request: _ok()),
        )


def test_llm_chat_3xx_not_success() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"location": "https://evil.test"})

    client = _client(handler)
    with pytest.raises(LLMError) as exc_info:
        client.chat([LLMMessage("user", "问题")])
    assert calls == 1
    assert "HTTP 302" in str(exc_info.value)


def test_llm_chat_top_level_not_object_raises() -> None:
    client = _client(lambda request: httpx.Response(200, json=[]))
    with pytest.raises(LLMError):
        client.chat([LLMMessage("user", "问题")])