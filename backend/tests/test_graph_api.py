"""S4-5 图谱接口：权限、列表、单条审核、批量审核、202 入队、统计。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.schemas.kp import GraphEdgeOut, GraphEdgePage, GraphStatsOut
from app.services import graph_service

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


def _user(role: str = "teacher") -> User:
    user = User(
        username=f"{role}_s45",
        nickname=role,
        grade="高二",
        role=role,
        password_hash="x",
    )
    user.id = 9 if role != "student" else 50
    return user


class FakeSession:
    def __init__(self, user: User) -> None:
        self.user = user

    def get(self, model, pk):
        return self.user if model is User else None

    def flush(self):
        return None

    def scalar(self, statement):
        # get_current_user 走 select(User) → 必须返回用户；其余计数语句返回 0
        return self.user if "users" in str(statement) else 0

    def execute(self, statement):
        class _Rows:
            def all(self):
                return []

        return _Rows()

    def scalars(self, statement):
        return iter([])


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(user: User) -> None:
    app.dependency_overrides[get_db] = lambda: FakeSession(user)


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


def _edge_out() -> GraphEdgeOut:
    return GraphEdgeOut(
        id=1,
        src_kp_id=2,
        src_name="函数单调性",
        dst_kp_id=8,
        dst_name="导数应用",
        relation="prerequisite",
        weight=0.82,
        source="ai",
        review_status="approved",
        reviewed_at=NOW,
        created_at=NOW,
    )


def test_edges_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/kp/graph/edges")
    assert resp.status_code == 401


def test_edges_forbidden_for_student(client: TestClient) -> None:
    student = _user("student")
    _wire(student)
    resp = client.get("/api/v1/kp/graph/edges", headers=_headers(student))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_edges_returns_page(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    teacher = _user()
    _wire(teacher)
    monkeypatch.setattr(
        graph_service,
        "list_edges",
        lambda session, **kwargs: GraphEdgePage(
            items=[_edge_out()], total=1, page=1, page_size=20
        ),
    )
    resp = client.get("/api/v1/kp/graph/edges", headers=_headers(teacher))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["src_name"] == "函数单调性"


def test_review_single_returns_edge(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    teacher = _user()
    _wire(teacher)
    monkeypatch.setattr(
        graph_service,
        "review_edge",
        lambda session, *, edge_id, approve, reviewer: object(),
    )
    monkeypatch.setattr(graph_service, "edge_out", lambda session, edge: _edge_out())
    resp = client.post(
        "/api/v1/kp/graph/edges/1/review", json={"approve": True}, headers=_headers(teacher)
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["review_status"] == "approved"


def test_review_batch_returns_counts(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    teacher = _user()
    _wire(teacher)
    monkeypatch.setattr(graph_service, "review_edges", lambda session, **kwargs: (2, 1))
    resp = client.post(
        "/api/v1/kp/graph/edges/review",
        json={"edge_ids": [1, 2, 999], "approve": False},
        headers=_headers(teacher),
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == {"updated": 2, "skipped": 1}


def test_review_batch_rejects_empty_ids(client: TestClient) -> None:
    teacher = _user()
    _wire(teacher)
    resp = client.post(
        "/api/v1/kp/graph/edges/review",
        json={"edge_ids": [], "approve": True},
        headers=_headers(teacher),
    )
    assert resp.status_code == 422


def test_build_enqueues_task(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    teacher = _user()
    _wire(teacher)

    class _Task:
        id = 77
        user_id = 9
        name = "graph.build"
        status = "pending"
        attempts = 0
        payload = {"subject_id": 7}
        result = None
        error = None
        created_at = NOW
        updated_at = NOW
        finished_at = None

    monkeypatch.setattr(graph_service, "enqueue_build", lambda session, **kwargs: _Task())
    resp = client.post(
        "/api/v1/kp/graph/build",
        json={"subject_id": 7, "limit": 10},
        headers=_headers(teacher),
    )
    assert resp.status_code == 202
    assert resp.json()["data"]["id"] == 77


def test_build_requires_subject_id(client: TestClient) -> None:
    teacher = _user()
    _wire(teacher)
    resp = client.post("/api/v1/kp/graph/build", json={}, headers=_headers(teacher))
    assert resp.status_code == 422


def test_stats_returns_counts(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    teacher = _user()
    _wire(teacher)
    monkeypatch.setattr(
        graph_service,
        "stats",
        lambda session, *, subject_id: GraphStatsOut(
            subject_id=subject_id,
            nodes=108,
            edges=0,
            by_relation={},
            by_status={},
            last_built_at=None,
        ),
    )
    resp = client.get("/api/v1/kp/graph/stats?subject_id=7", headers=_headers(teacher))
    assert resp.status_code == 200
    assert resp.json()["data"]["nodes"] == 108