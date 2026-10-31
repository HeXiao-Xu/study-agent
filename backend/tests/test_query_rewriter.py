"""S3-3 改写器：FakeLLM，禁止真实网络。"""
from __future__ import annotations

import json

import pytest

from app.ai.llm import LLMClient, LLMResponse
from app.ai.rag.query_rewriter import (
    HistoryTurn,
    RewriteError,
    render_prompt,
    rewrite_with_llm,
)


class FakeLLM(LLMClient):
    def __init__(self, *texts: str, error: Exception | None = None) -> None:
        super().__init__(model="fake-llm")
        self.texts = list(texts)
        self.error = error
        self.calls: list[dict] = []

    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
        self.calls.append(
            {
                "messages": list(messages),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "scene": scene,
            }
        )
        if self.error is not None:
            raise self.error
        text = self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]
        return LLMResponse(
            text=text,
            model="fake-llm",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            latency_ms=1,
            cost_yuan=0.00001,
        )


def _output(
    *,
    intent: str = "note_query",
    query: str = "函数单调性的前提条件是什么？",
    followup: bool = True,
    reply: str = "",
) -> str:
    return json.dumps(
        {
            "intent": intent,
            "rewritten_query": query,
            "is_followup": followup,
            "reply": reply,
        },
        ensure_ascii=False,
    )


def test_render_prompt_includes_history_and_question() -> None:
    prompt = render_prompt(
        "那它的前提条件呢？",
        [
            HistoryTurn(role="user", content="函数单调性是什么？"),
            HistoryTurn(role="assistant", content="单调递增。"),
        ],
    )

    assert "用户：函数单调性是什么？" in prompt
    assert "助手：单调递增。" in prompt
    assert "【当前问题】那它的前提条件呢？" in prompt
    assert "只输出这个 JSON" in prompt


def test_rewrite_returns_valid_output_and_metrics() -> None:
    client = FakeLLM(_output())

    call = rewrite_with_llm(
        "那它的前提条件呢？",
        history=[HistoryTurn(role="user", content="函数单调性是什么？")],
        llm_client=client,
        max_tokens=123,
    )

    assert call.output.intent == "note_query"
    assert call.output.rewritten_query == "函数单调性的前提条件是什么？"
    assert call.output.is_followup is True
    assert call.llm_calls == 1
    assert call.total_tokens == 15
    assert client.calls[0]["scene"] == "query_rewrite"
    assert client.calls[0]["temperature"] == 0.0
    assert client.calls[0]["max_tokens"] == 123
    assert "函数单调性是什么" in client.calls[0]["messages"][0].content


def test_rewrite_accepts_json_fence() -> None:
    client = FakeLLM("```json\n" + _output() + "\n```")

    call = rewrite_with_llm("那它的前提条件呢？", llm_client=client)

    assert call.output.intent == "note_query"


def test_rewrite_retries_invalid_json_then_succeeds() -> None:
    client = FakeLLM("not json", _output())

    call = rewrite_with_llm("那它的前提条件呢？", llm_client=client, max_retries=2)

    assert call.llm_calls == 2
    assert len(client.calls) == 2
    retry_messages = client.calls[1]["messages"]
    assert retry_messages[-2].role == "assistant"
    assert retry_messages[-2].content == "not json"
    assert retry_messages[-1].role == "user"
    assert "只输出一个 JSON 对象" in retry_messages[-1].content


def test_rewrite_exhausts_retries_and_raises_with_metrics() -> None:
    client = FakeLLM("not json")

    with pytest.raises(RewriteError) as exc_info:
        rewrite_with_llm("那它的前提条件呢？", llm_client=client, max_retries=2)

    assert len(client.calls) == 3
    assert exc_info.value.llm_calls == 3
    assert exc_info.value.total_tokens == 45
    assert "not json" not in str(exc_info.value)


@pytest.mark.parametrize(
    "payload",
    [
        _output(query=""),
        _output(intent="chitchat", query="", reply=""),
        _output(intent="unknown_intent"),
    ],
)
def test_rewrite_rejects_invalid_output(payload: str) -> None:
    client = FakeLLM(payload)

    with pytest.raises(RewriteError):
        rewrite_with_llm("那它的前提条件呢？", llm_client=client, max_retries=0)


def test_rewrite_without_history_keeps_question() -> None:
    client = FakeLLM(_output(query="函数的定义域怎么求？", followup=False))

    call = rewrite_with_llm("函数的定义域怎么求？", llm_client=client)

    prompt = client.calls[0]["messages"][0].content
    assert "用户：" not in prompt
    assert call.output.is_followup is False


def test_render_prompt_missing_template_raises(monkeypatch, tmp_path) -> None:
    import app.ai.rag.query_rewriter as module

    monkeypatch.setattr(module, "PROMPT_PATH", tmp_path / "missing.md")

    with pytest.raises(RewriteError):
        render_prompt("问题", [])