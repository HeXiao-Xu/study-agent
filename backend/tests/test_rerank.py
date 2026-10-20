"""S1-5 Rerank 适配器测试：HTTP 全 mock（spec §8.1）。"""
from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
import tiktoken

from app.ai.rerank import (
    DashScopeRerankClient,
    LocalRerankClient,
    RerankCandidate,
    RerankError,
)


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    **kwargs: object,
) -> DashScopeRerankClient:
    kwargs.setdefault("sleep", lambda _: None)
    return DashScopeRerankClient(
        api_key="sk-test",
        base_url="https://example.test/api/v1",
        model="qwen3-rerank",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def _ok(results: list[dict], tokens: int = 79) -> httpx.Response:
    return httpx.Response(
        200,
        json={"output": {"results": results}, "usage": {"total_tokens": tokens}},
    )


def test_local_rerank_raises() -> None:
    with pytest.raises(RerankError, match="占位"):
        LocalRerankClient().rerank("查询", [RerankCandidate(id=1, content="候选")])


def test_rerank_success_sends_one_batch_and_sorts() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return _ok([
            {"index": 2, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.4},
        ])

    client = _client(handler)
    candidates = [
        RerankCandidate(id=11, content="块一"),
        RerankCandidate(id=12, content="块二"),
        RerankCandidate(id=13, content="块三"),
    ]
    response = client.rerank("函数的单调性", candidates, top_n=2)

    assert len(seen) == 1
    assert seen[0]["model"] == "qwen3-rerank"
    assert seen[0]["input"]["query"] == "函数的单调性"
    assert seen[0]["input"]["documents"] == ["块一", "块二", "块三"]
    assert seen[0]["parameters"] == {"return_documents": False, "top_n": 2}
    assert [item.id for item in response.scores] == [13, 11]
    assert [item.score for item in response.scores] == [0.9, 0.4]
    assert response.tokens == 79
    assert response.cost_yuan == pytest.approx(79 * 0.5 / 1_000_000)
    assert client.request_count == 1


def test_rerank_truncates_query_and_documents() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return _ok([{"index": 0, "relevance_score": 0.8}])

    client = _client(handler, max_doc_tokens=20)
    long_text = "数学函数单调性" * 500
    client.rerank(long_text, [RerankCandidate(id=1, content=long_text)], top_n=1)

    enc = tiktoken.get_encoding("cl100k_base")
    assert len(enc.encode(seen["input"]["query"])) <= 20
    assert len(enc.encode(seen["input"]["documents"][0])) <= 20


def test_rerank_retries_500_then_success() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500, json={"message": "temporary"})
        return _ok([{"index": 0, "relevance_score": 0.7}])

    client = _client(handler, max_retries=2, sleep=sleeps.append)
    response = client.rerank("q", [RerankCandidate(id=1, content="c")])

    assert len(calls) == 2
    assert len(sleeps) == 1
    assert client.request_count == 2
    assert response.scores[0].score == 0.7


def test_rerank_timeout_exhausts_retries() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectTimeout("boom")

    client = _client(handler, max_retries=1)
    with pytest.raises(RerankError) as exc_info:
        client.rerank("q", [RerankCandidate(id=1, content="c")])

    assert exc_info.value.retryable is True
    assert len(calls) == 2


def test_rerank_400_not_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"message": "bad request"})

    client = _client(handler, max_retries=2)
    with pytest.raises(RerankError) as exc_info:
        client.rerank("q", [RerankCandidate(id=1, content="c")])

    assert len(calls) == 1
    assert exc_info.value.status_code == 400
    assert exc_info.value.retryable is False


def test_rerank_malformed_response_raises() -> None:
    client = _client(lambda request: _ok([]))
    with pytest.raises(RerankError, match="results"):
        client.rerank("q", [RerankCandidate(id=1, content="c")])


def test_rerank_empty_candidates_no_request() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _ok([{"index": 0, "relevance_score": 1.0}])

    client = _client(handler)
    response = client.rerank("q", [])

    assert response.scores == []
    assert response.tokens == 0
    assert calls == []


def test_rerank_invalid_top_n() -> None:
    client = _client(lambda request: _ok([{"index": 0, "relevance_score": 1.0}]))
    with pytest.raises(ValueError, match="top_n"):
        client.rerank("q", [RerankCandidate(id=1, content="c")], top_n=0)


def test_rerank_duplicate_index_raises() -> None:
    client = _client(lambda request: _ok([
        {"index": 0, "relevance_score": 0.9},
        {"index": 0, "relevance_score": 0.8},
    ]))
    with pytest.raises(RerankError, match="重复"):
        client.rerank("q", [RerankCandidate(id=1, content="c")])


def test_rerank_top_level_not_object_raises() -> None:
    client = _client(lambda request: httpx.Response(200, json=[]))
    with pytest.raises(RerankError, match="顶层"):
        client.rerank("q", [RerankCandidate(id=1, content="c")])


def test_rerank_malformed_usage_tokens_defaults_zero() -> None:
    client = _client(lambda request: httpx.Response(
        200,
        json={
            "output": {"results": [{"index": 0, "relevance_score": 0.5}]},
            "usage": {"total_tokens": None},
        },
    ))
    response = client.rerank("q", [RerankCandidate(id=1, content="c")])
    assert response.tokens == 0
    assert response.cost_yuan == 0.0


def test_rerank_index_out_of_range_raises() -> None:
    client = _client(lambda request: _ok([{"index": 3, "relevance_score": 0.9}]))
    with pytest.raises(RerankError, match="越界"):
        client.rerank("q", [RerankCandidate(id=1, content="c")])


def test_rerank_429_retry_after_then_success() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "1"},
                json={"message": "rate limited"},
            )
        return _ok([{"index": 0, "relevance_score": 0.7}])

    client = _client(handler, max_retries=2, sleep=sleeps.append)
    response = client.rerank("q", [RerankCandidate(id=1, content="c")])

    assert len(calls) == 2
    assert sleeps == [1.0]
    assert response.scores[0].score == 0.7


def test_rerank_400_does_not_echo_body() -> None:
    body_text = "SENSITIVE_DOCUMENT_TEXT"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": body_text})

    client = _client(handler, max_retries=0)
    with pytest.raises(RerankError) as exc_info:
        client.rerank("q", [RerankCandidate(id=1, content="c")])

    assert body_text not in str(exc_info.value)


def test_rerank_tokenizer_failure_raises_rerank_error(monkeypatch) -> None:
    def broken_encoding():
        raise OSError("bpe not available")

    monkeypatch.setattr("app.ai.rerank.client._encoding_get", broken_encoding)
    client = _client(lambda request: _ok([{"index": 0, "relevance_score": 0.5}]))
    with pytest.raises(RerankError, match="tokenizer"):
        client.rerank("q", [RerankCandidate(id=1, content="c")])


def test_rerank_partial_results_raises() -> None:
    client = _client(lambda request: _ok([{"index": 0, "relevance_score": 0.9}]))
    candidates = [
        RerankCandidate(id=1, content="a"),
        RerankCandidate(id=2, content="b"),
    ]
    with pytest.raises(RerankError, match="不完整"):
        client.rerank("q", candidates, top_n=2)