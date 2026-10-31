"""S3-1 管理员重建索引接口测试（spec §7）：TestClient + 依赖覆盖。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.schemas.indexing import RebuildProgress, RebuildStart
from app.services import index_service
from app.tasks.queue import get_task_queue


class FakeSession:
    def __init__(self, *, user: User | None = None) -> None:
        self.user = user
        self.commits = 0

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        raise AssertionError(f"unexpected entity: {entity}")

    def get(self, entity: type, pk: int):
        raise AssertionError(f"unexpected get: {entity}")

    def add(self, instance: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return None

    def refresh(self, instance: object) -> None:
        return None

    def scalars(self, statement: object):
        return iter([])

    def execute(self, statement: object):
        return None


class FakeQueue:
    def enqueue(self, name: str, task_id: int) -> None:
        return None


def _user(user_id: int = 1, *, role: str = "admin", username: str = "admin_1") -> User:
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


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _override(session: FakeSession) -> None:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_task_queue] = lambda: FakeQueue()


def test_rebuild_requires_admin(client: TestClient) -> None:
    teacher = _user(2, role="teacher", username="teacher_1")
    _override(FakeSession(user=teacher))
    resp = client.post("/api/v1/admin/index/rebuild", headers=_headers(teacher))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_rebuild_requires_token(client: TestClient) -> None:
    _override(FakeSession())
    resp = client.post("/api/v1/admin/index/rebuild")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_rebuild_returns_202(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _user()
    _override(FakeSession(user=admin))
    monkeypatch.setattr(
        index_service,
        "start_rebuild",
        lambda session, *, owner, queue: RebuildStart(
            run_id="a" * 32, total_notes=4, purged_chunks=2
        ),
    )

    resp = client.post("/api/v1/admin/index/rebuild", headers=_headers(admin))

    assert resp.status_code == 202
    assert resp.json()["data"] == {
        "run_id": "a" * 32,
        "total_notes": 4,
        "purged_chunks": 2,
    }


def test_rebuild_returns_500_when_queue_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.exceptions import TaskQueueUnavailableError

    admin = _user()
    _override(FakeSession(user=admin))

    def fail(session, *, owner, queue):
        raise TaskQueueUnavailableError()

    monkeypatch.setattr(index_service, "start_rebuild", fail)

    resp = client.post("/api/v1/admin/index/rebuild", headers=_headers(admin))

    assert resp.status_code == 500
    assert resp.json()["code"] == 50000


def test_progress_returns_fields(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _user()
    _override(FakeSession(user=admin))
    progress = RebuildProgress(
        run_id="a" * 32,
        total=3,
        pending=0,
        running=0,
        succeeded=3,
        failed=0,
        percent=100,
        chunks=11,
        started_at=None,
        finished_at=None,
        failures=[],
    )
    monkeypatch.setattr(
        index_service, "get_rebuild_progress", lambda session, *, run_id: progress
    )

    resp = client.get(
        f"/api/v1/admin/index/runs/{'a' * 32}", headers=_headers(admin)
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["percent"] == 100
    assert data["chunks"] == 11
    assert data["failures"] == []
    assert set(data) == {
        "run_id",
        "total",
        "pending",
        "running",
        "succeeded",
        "failed",
        "percent",
        "chunks",
        "started_at",
        "finished_at",
        "failures",
    }


def test_progress_unknown_run_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.exceptions import NotFoundError

    admin = _user()
    _override(FakeSession(user=admin))

    def missing(session, *, run_id):
        raise NotFoundError("索引重建记录不存在")

    monkeypatch.setattr(index_service, "get_rebuild_progress", missing)

    resp = client.get(
        f"/api/v1/admin/index/runs/{'b' * 32}", headers=_headers(admin)
    )

    assert resp.status_code == 404
    assert resp.json()["code"] == 40400


def test_progress_rejects_bad_run_id(client: TestClient) -> None:
    admin = _user()
    _override(FakeSession(user=admin))

    resp = client.get("/api/v1/admin/index/runs/not-a-run-id", headers=_headers(admin))

    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_progress_forbidden_for_student(client: TestClient) -> None:
    student = _user(3, role="student", username="student_1")
    _override(FakeSession(user=student))

    resp = client.get(
        f"/api/v1/admin/index/runs/{'a' * 32}", headers=_headers(student)
    )

    assert resp.status_code == 403