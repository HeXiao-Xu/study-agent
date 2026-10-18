"""S1-3 Embedding 适配器测试：分批/重试/维度/Key 不泄漏（spec §4/§10）。"""
from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from app.ai.embedding.base import BatchStats
from app.ai.embedding.errors import EmbeddingError
from app.ai.embedding.local import LocalEmbeddingClient
from app.ai.embedding.openai_compat import OpenAICompatibleEmbeddingClient


def _client(handler: Callable[[httpx.Request], httpx.Response], **kwargs) -> OpenAICompatibleEmbeddingClient:
    return OpenAICompatibleEmbeddingClient(
        api_key="sk-secret-test",
        base_url="https://example.invalid/v1",
        model="fake-embed",
        dim=4,
        batch_size=10,
        max_retries=kwargs.pop("max_retries", 0),
        sleep=kwargs.pop("sleep", lambda _s: None),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def _ok_response(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    items = []
    for i, text in enumerate(body["input"]):
        items.append({"embedding": [float(text[1:])] * 4, "index": i})
    return httpx.Response(200, json={"data": items, "usage": {"total_tokens": len(items) * 3}})


def test_encode_batches_and_preserves_order() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(len(body["input"]))
        return _ok_response(request)

    client = _client(handler)
    vectors = client.encode([f"t{i}" for i in range(25)])
    assert calls == [10, 10, 5]
    assert [int(v[0]) for v in vectors] == list(range(25))
    assert len(vectors) == 25
    assert client.usage_tokens == 75


def test_on_batch_reports_each_batch() -> None:
    stats: list[BatchStats] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return _ok_response(request)

    client = _client(handler)
    client.encode([f"t{i}" for i in range(25)], on_batch=stats.append)
    assert [(s.batch_index, s.batch_size) for s in stats] == [(0, 10), (1, 10), (2, 5)]


def test_429_retries_then_succeeds() -> None:
    sleeps: list[float] = []
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={"error": {"message": "rate"}})
        return _ok_response(request)

    client = _client(handler, max_retries=1, sleep=sleeps.append)
    vectors = client.encode(["t0"])
    assert len(vectors) == 1
    assert calls["n"] == 2
    assert sleeps == [2.0]  # 尊重 Retry-After


def test_retry_exhausted_raises_embedding_error() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, json={"error": {"message": "rate"}})

    client = _client(handler, max_retries=2)
    with pytest.raises(EmbeddingError) as exc:
        client.encode(["t0"])
    assert calls["n"] == 3
    assert exc.value.retryable is True
    assert "sk-secret-test" not in str(exc.value)


def test_401_is_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    client = _client(handler, max_retries=3)
    with pytest.raises(EmbeddingError):
        client.encode(["t0"])
    assert calls["n"] == 1


def test_dimension_mismatch_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2], "index": 0}], "usage": {"total_tokens": 1}})

    client = _client(handler)
    with pytest.raises(EmbeddingError, match="维度"):
        client.encode(["t0"])


def test_empty_input_sends_no_request() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _ok_response(request)

    client = _client(handler)
    assert client.encode([]) == []
    assert calls["n"] == 0


def test_repr_hides_key() -> None:
    client = _client(_ok_response)
    assert "sk-secret-test" not in repr(client)
    assert "sk-secret-test" not in str(client)


def test_local_client_is_placeholder() -> None:
    with pytest.raises(NotImplementedError, match="占位"):
        LocalEmbeddingClient().encode(["x"])
