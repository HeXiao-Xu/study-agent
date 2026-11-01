"""S3-9 在线评测客户端：MockTransport，不触网。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval.api_client import (  # noqa: E402
    OnlineClient,
    OnlineEvalError,
    login,
    normalize_base_url,
    parse_sse_events,
)


def test_normalize_base_url() -> None:
    assert (
        normalize_base_url("http://127.0.0.1:8000/")
        == "http://127.0.0.1:8000/api/v1"
    )
    assert (
        normalize_base_url("http://127.0.0.1:8000/api/v1")
        == "http://127.0.0.1:8000/api/v1"
    )


def test_parse_sse_events_meta_delta_done() -> None:
    lines = [
        "event: meta",
        'data: {"conversation_id":"7","citations":[]}',
        "",
        "event: delta",
        'data: {"text":"你"}',
        "",
        "event: delta",
        'data: {"text":"好"}',
        "",
        "event: done",
        'data: {"refused":false,"tokens":3}',
        "",
    ]
    events = list(parse_sse_events(lines))
    assert [event for event, _ in events] == ["meta", "delta", "delta", "done"]
    assert events[1][1]["text"] == "你"


def test_parse_sse_events_raises_on_bad_json() -> None:
    with pytest.raises(OnlineEvalError, match="SSE"):
        list(parse_sse_events(["event: delta", "data: not-json", ""]))


def _envelope(data: object, *, code: int = 0) -> httpx.Response:
    return httpx.Response(200, json={"code": code, "data": data, "trace_id": "t"})


def test_search_sends_auth_and_retrieval_mode() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _envelope(
            {
                "query": "函数",
                "top_k": 5,
                "rerank": False,
                "elapsed_ms": 12,
                "embedding_ms": 8,
                "hits": [{"chunk_id": 250}, {"chunk_id": 254}],
            }
        )

    client = OnlineClient(
        "http://testserver", "token-123", transport=httpx.MockTransport(handler)
    )
    result = client.search("函数", "vector", top_k=5)
    client.close()

    assert result.chunk_ids == [250, 254]
    assert result.latency_ms == 12
    assert result.rerank is False
    assert captured[0].headers["authorization"] == "Bearer token-123"
    assert json.loads(captured[0].content)["retrieval"] == "vector"


def test_ask_collects_citations_text_and_cost() -> None:
    body = "\n".join(
        [
            "event: meta",
            'data: {"conversation_id":"7","citations":[{"chunk_id":250,"title":"属性","heading_path":"单调性","snippet":"定义"}]}',
            "",
            "event: delta",
            'data: {"text":"答"}',
            "",
            "event: done",
            'data: {"refused":false,"tokens":9,"latency_ms":120,"cost_yuan":0.0012,"conversation_id":"7"}',
            "",
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/qa/ask"
        return httpx.Response(
            200,
            text=body,
            headers={"content-type": "text/event-stream"},
        )

    client = OnlineClient(
        "http://testserver", "token-123", transport=httpx.MockTransport(handler)
    )
    answer = client.ask("单调性是什么")
    client.close()

    assert answer.text == "答"
    assert answer.citations[0].chunk_id == 250
    assert answer.cost_yuan == pytest.approx(0.0012)
    assert answer.conversation_id == "7"


def test_ask_raises_on_error_event() -> None:
    body = "\n".join(
        [
            "event: error",
            'data: {"code":50000,"message":"生成失败"}',
            "",
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=body,
            headers={"content-type": "text/event-stream"},
        )

    client = OnlineClient(
        "http://testserver", "token-123", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(OnlineEvalError, match="生成失败"):
        client.ask("q")
    client.close()


def test_login_returns_access_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/auth/login"
        assert json.loads(request.content) == {
            "username": "test1",
            "password": "pw",
        }
        return _envelope({"access_token": "jwt-abc", "token_type": "bearer"})

    token = login(
        "http://testserver",
        "test1",
        "pw",
        transport=httpx.MockTransport(handler),
    )
    assert token == "jwt-abc"