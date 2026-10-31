"""S3-3 改写服务：fake rewriter，不触库、不调外部 API。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.llm.errors import LLMError
from app.ai.rag.query_rewriter import (
    HistoryTurn,
    RewriteCall,
    RewriteError,
    RewriteOutput,
)
from app.services import query_rewrite


class FakeRewriter:
    def __init__(self, call: RewriteCall | None = None, error: Exception | None = None) -> None:
        self.call = call
        self.error = error
        self.calls: list[dict] = []

    def __call__(self, question, *, history=None, llm_client=None, max_tokens=400, max_retries=2):
        self.calls.append(
            {
                "question": question,
                "history": list(history or []),
                "max_tokens": max_tokens,
            }
        )
        if self.error is not None:
            raise self.error
        assert self.call is not None
        return self.call


def _settings(**overrides: object) -> SimpleNamespace:
    values = {
        "query_rewrite_enabled": True,
        "query_rewrite_max_history_turns": 3,
        "query_rewrite_history_content_chars": 300,
        "query_rewrite_max_tokens": 400,
        "query_rewrite_cache_ttl_seconds": 3600,
        "query_rewrite_cache_size": 256,
        "llm_model": "qwen-plus",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _call(
    *,
    intent: str = "note_query",
    query: str = "函数单调性的前提条件是什么？",
    followup: bool = True,
    reply: str = "",
) -> RewriteCall:
    return RewriteCall(
        output=RewriteOutput(
            intent=intent,
            rewritten_query=query,
            is_followup=followup,
            reply=reply,
        ),
        llm_calls=1,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cost_yuan=0.00001,
        latency_ms=20,
    )


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    query_rewrite.clear_cache()
    yield
    query_rewrite.clear_cache()


@pytest.mark.parametrize("question", ["", "   "])
def test_rewrite_rejects_blank_question(monkeypatch, question: str) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    with pytest.raises(ValueError, match="question"):
        query_rewrite.rewrite_query(question)


def test_rewrite_rejects_too_long_question(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    with pytest.raises(ValueError, match="过长"):
        query_rewrite.rewrite_query("x" * 501)


def test_rewrite_keeps_only_last_three_user_turns(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    fake = FakeRewriter(call=_call())
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", fake)
    history = []
    for index in range(5):
        history.append(HistoryTurn(role="user", content=f"u{index}"))
        history.append(HistoryTurn(role="assistant", content=f"a{index}"))

    query_rewrite.rewrite_query("那它呢？", history=history)

    sent = fake.calls[0]["history"]
    assert [turn.content for turn in sent if turn.role == "user"] == ["u2", "u3", "u4"]
    assert len(sent) == 6


def test_rewrite_truncates_long_history_content(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    fake = FakeRewriter(call=_call())
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", fake)

    query_rewrite.rewrite_query(
        "那它呢？",
        history=[HistoryTurn(role="user", content="x" * 400)],
    )

    assert len(fake.calls[0]["history"][0].content) == 300


def test_rewrite_maps_success_and_caches(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    fake = FakeRewriter(call=_call())
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", fake)

    first = query_rewrite.rewrite_query("那它呢？")
    second = query_rewrite.rewrite_query("那它呢？")

    assert first.intent == "note_query"
    assert first.rewritten_query == "函数单调性的前提条件是什么？"
    assert first.degraded is False
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.llm_calls == 0
    assert second.total_tokens == 0
    assert second.latency_ms == 0
    assert len(fake.calls) == 1


def test_rewrite_cache_expires(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    fake = FakeRewriter(call=_call())
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", fake)
    now = [100.0]
    monkeypatch.setattr(query_rewrite.time, "monotonic", lambda: now[0])

    query_rewrite.rewrite_query("那它呢？")
    now[0] += 3601
    second = query_rewrite.rewrite_query("那它呢？")

    assert second.cache_hit is False
    assert len(fake.calls) == 2


def test_rewrite_cache_separates_history(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    fake = FakeRewriter(call=_call())
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", fake)

    query_rewrite.rewrite_query("那它呢？", history=[HistoryTurn("user", "函数")])
    query_rewrite.rewrite_query("那它呢？", history=[HistoryTurn("user", "数列")])

    assert len(fake.calls) == 2


def test_rewrite_use_cache_false_always_calls(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    fake = FakeRewriter(call=_call())
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", fake)

    query_rewrite.rewrite_query("那它呢？", use_cache=False)
    query_rewrite.rewrite_query("那它呢？", use_cache=False)

    assert len(fake.calls) == 2


def test_rewrite_llm_error_falls_back_to_original(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        query_rewrite, "rewrite_with_llm", FakeRewriter(error=LLMError("boom"))
    )

    result = query_rewrite.rewrite_query("那它呢？")

    assert result.degraded is True
    assert result.intent == "note_query"
    assert result.rewritten_query == "那它呢？"
    assert result.reply == query_rewrite.FALLBACK_REPLY
    assert result.error == "LLMError"
    assert result.llm_calls == 0


def test_rewrite_error_preserves_metrics(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    error = RewriteError(
        "bad",
        llm_calls=3,
        prompt_tokens=30,
        completion_tokens=10,
        total_tokens=40,
        cost_yuan=0.001,
    )
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", FakeRewriter(error=error))

    result = query_rewrite.rewrite_query("那它呢？")

    assert result.degraded is True
    assert result.llm_calls == 3
    assert result.total_tokens == 40
    assert result.cost_yuan == 0.001
    assert result.error == "RewriteError"


def test_rewrite_disabled_passthrough_without_llm(monkeypatch) -> None:
    monkeypatch.setattr(
        query_rewrite,
        "get_settings",
        lambda: _settings(query_rewrite_enabled=False),
    )
    fake = FakeRewriter(call=_call())
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", fake)

    result = query_rewrite.rewrite_query(
        "  那它呢？  ",
        history=[HistoryTurn("user", "函数")],
    )

    assert result.intent == "note_query"
    assert result.rewritten_query == "那它呢？"
    assert result.is_followup is True
    assert result.degraded is False
    assert result.llm_calls == 0
    assert fake.calls == []


def test_rewrite_chitchat_keeps_reply(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    fake = FakeRewriter(
        call=_call(intent="chitchat", query="", followup=False, reply="你好，我是学习助手。")
    )
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", fake)

    result = query_rewrite.rewrite_query("你好")

    assert result.intent == "chitchat"
    assert result.reply == "你好，我是学习助手。"
    assert result.rewritten_query == ""