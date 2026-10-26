"""S2-7 任务接口：TestClient + 依赖覆盖，不连库不连 Redis。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.async_task import AsyncTask
from app.models.user import User
from app.tasks.queue import get_task_queue


class FakeSession:
    def __init__(self, *, user: User | None = None) -> None:
        self.user = user
        self.rows: dict[int, AsyncTask] = {}
        self.added: list[AsyncTask] = []

    def scalar(self, statement: object):
        return self.user

    def get(self, entity: type, pk: int):
        return self.rows.get(pk) if entity is AsyncTask else None

    def add(self, instance: AsyncTask) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        for row in self.added:
            if row.id is None:
                row.id = 31
            row.created_at = datetime.now(timezone.utc)
            self.rows[row.id] = row

    def rollback(self) -> None:
        pass

    def refresh(self, instance: AsyncTask) -> None:
        if instance.id is None:
            instance.id = 31
        if instance.created_at is None:
            instance.created_at = datetime.now(timezone.utc)


class FakeQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def enqueue(self, name: str, task_id: int) -> None:
        self.calls.append((name, task_id))


def _user(user_id: int = 1, *, role: str = "student") -> User:
    user = User(
        username=f"student_{user_id}",
        password_hash="hash",
        nickname=f"测试用户_{user_id}",
        grade="高一",
        role=role,
    )
    user.id = user_id
    return user


def _task(*, owner_id: int = 1, status: str = "running") -> AsyncTask:
    task = AsyncTask(
        user_id=owner_id,
        name="demo.sleep",
        status=status,
        payload={"seconds": 5, "fail": False},
        attempts=1,
    )
    task.id = 31
    task.created_at = datetime.now(timezone.utc)
    task.started_at = datetime.now(timezone.utc)
    return task


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(session: FakeSession, queue: FakeQueue | None = None) -> FakeQueue:
    fake_queue = queue or FakeQueue()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_task_queue] = lambda: fake_queue
    return fake_queue


def test_submit_demo_returns_202_pending(client: TestClient) -> None:
    user = _user()
    queue = _wire(FakeSession(user=user))
    resp = client.post("/api/v1/tasks/demo", json={"seconds": 5}, headers=_headers(user))
    assert resp.status_code == 202
    assert resp.json()["data"]["status"] == "pending"
    assert resp.json()["data"]["name"] == "demo.sleep"
    assert queue.calls == [("demo.sleep", 31)]


def test_get_task_returns_detail(client: TestClient) -> None:
    user = _user()
    session = FakeSession(user=user)
    session.rows[31] = _task()
    _wire(session)
    resp = client.get("/api/v1/tasks/31", headers=_headers(user))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "running"
    assert data["attempts"] == 1
    assert data["payload"] == {"seconds": 5, "fail": False}


def test_get_other_task_returns_403(client: TestClient) -> None:
    user = _user(2)
    session = FakeSession(user=user)
    session.rows[31] = _task(owner_id=1)
    _wire(session)
    resp = client.get("/api/v1/tasks/31", headers=_headers(user))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_get_missing_task_returns_404(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    resp = client.get("/api/v1/tasks/99", headers=_headers(user))
    assert resp.status_code == 404
    assert resp.json()["code"] == 40400


def test_submit_requires_token(client: TestClient) -> None:
    _wire(FakeSession())
    resp = client.post("/api/v1/tasks/demo", json={"seconds": 5})
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_submit_forbidden_for_teacher(client: TestClient) -> None:
    user = _user(role="teacher")
    _wire(FakeSession(user=user))
    resp = client.post("/api/v1/tasks/demo", json={"seconds": 5}, headers=_headers(user))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_submit_invalid_seconds_returns_422(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    resp = client.post("/api/v1/tasks/demo", json={"seconds": 0}, headers=_headers(user))
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200