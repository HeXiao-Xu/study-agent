"""S3-2 检索接口测试（spec §6）：TestClient + 依赖覆盖，不触库、不调外部 API。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.schemas.retrieval import (
    RetrievalDebug,
    RetrievalHit,
    RetrievalSearchResponse,
)
from app.services import retrieval_service


class FakeSession:
    def __init__(self, user: User | None = None) -> None:
        self.user = user

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        raise AssertionError(f"unexpected entity: {entity}")

    def get(self, entity: type, pk: int):
        raise AssertionError(f"unexpected get: {entity}")

    def execute(self, statement: object):
        raise AssertionError("搜索路径不应触库（service 已被替换）")


def _user(user_id: int = 1, *, role: str = "student", username: str = "student_1") -> User:
    user = User(
        username=username,
        password_hash="hash",
        nickname=f"测试用户_{user_id}",
        grade=None,
        role=role,
    )
    user.id = user_id
    user.created_at = datetime.now(timezone.utc)
    return user


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


def _hit() -> RetrievalHit:
    return RetrievalHit(
        chunk_id=25,
        note_id=54,
        note_title="函数笔记",
        chunk_index=4,
        chunk_type="note",
        content="函数的单调性",
        snippet="函数的单调性",
        heading_path="函数/单调性",
        page_no=3,
        rrf_score=0.03,
    )


def _response() -> RetrievalSearchResponse:
    return RetrievalSearchResponse(
        query="函数",
        top_k=6,
        rerank=False,
        elapsed_ms=12,
        embedding_ms=9,
        hits=[_hit()],
    )


def _debug() -> RetrievalDebug:
    return RetrievalDebug(
        tsquery="函数",
        vector_ms=2,
        fulltext_ms=1,
        vector=[_hit()],
        fulltext=[_hit()],
        fused=[_hit()],
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    def fake_search(session: object, **kwargs: Any) -> RetrievalSearchResponse:
        response = _response()
        if kwargs.get("debug"):
            return response.model_copy(update={"debug": _debug()})
        return response

    monkeypatch.setattr(retrieval_service, "search_chunks", fake_search)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _override_user(user: User) -> None:
    app.dependency_overrides[get_db] = lambda: FakeSession(user)


def test_search_requires_login(client: TestClient) -> None:
    response = client.post("/api/v1/retrieval/search", json={"query": "函数"})
    assert response.status_code == 401
    assert response.json()["code"] == 40100


def test_search_rejects_teacher(client: TestClient) -> None:
    user = _user(role="teacher", username="teacher_1")
    _override_user(user)

    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "函数"},
        headers=_headers(user),
    )

    assert response.status_code == 403
    assert response.json()["code"] == 40300


def test_search_returns_hits(client: TestClient) -> None:
    user = _user()
    _override_user(user)

    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "函数", "top_k": 6, "rerank": False},
        headers=_headers(user),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["query"] == "函数"
    assert data["hits"][0]["chunk_id"] == 25
    assert data["hits"][0]["note_title"] == "函数笔记"
    assert data["debug"] is None
    assert data["rerank"] is False


def test_search_debug_returns_candidates(client: TestClient) -> None:
    user = _user()
    _override_user(user)

    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "函数", "debug": True, "rerank": False},
        headers=_headers(user),
    )

    data = response.json()["data"]
    assert data["debug"]["vector"][0]["chunk_id"] == 25
    assert data["debug"]["fused"][0]["snippet"] == "函数的单调性"


def test_search_empty_query_is_422(client: TestClient) -> None:
    user = _user()
    _override_user(user)
    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": ""},
        headers=_headers(user),
    )
    assert response.status_code == 422


def test_search_invalid_top_k_is_422(client: TestClient) -> None:
    user = _user()
    _override_user(user)
    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "函数", "top_k": 0},
        headers=_headers(user),
    )
    assert response.status_code == 422


def test_search_inverted_dates_is_422(client: TestClient) -> None:
    user = _user()
    _override_user(user)
    response = client.post(
        "/api/v1/retrieval/search",
        json={
            "query": "函数",
            "scope": {"start_date": "2026-10-31", "end_date": "2026-10-01"},
        },
        headers=_headers(user),
    )
    assert response.status_code == 422


def test_search_unknown_scope_field_is_422(client: TestClient) -> None:
    user = _user()
    _override_user(user)
    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "函数", "scope": {"notebook_id": 1}},
        headers=_headers(user),
    )
    assert response.status_code == 422


def test_search_empty_chunk_types_is_422(client: TestClient) -> None:
    user = _user()
    _override_user(user)
    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "函数", "scope": {"chunk_types": []}},
        headers=_headers(user),
    )
    assert response.status_code == 422