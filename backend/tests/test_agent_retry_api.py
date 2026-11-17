"""S6-6 失败任务重跑：202/403/404/409。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.exceptions import ConflictError
from app.core.security import create_access_token
from app.main import app
from app.services import agent_service
from app.tasks.queue import get_task_queue


class FakeSession:
    def __init__(self, user):  # noqa: ANN001
        self.user = user

    def scalar(self, statement):  # noqa: ANN001, ANN201
        return self.user


class FakeQueue:
    def enqueue(self, name, task_id):  # noqa: ANN001
        return None


def _user(role="student"):  # noqa: ANN001
    from app.models.user import User

    user = User(
        username="retry_s66", nickname="r", grade="高二", role=role, password_hash="x"
    )
    user.id = 18
    return user


def _client(user):  # noqa: ANN001
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    app.dependency_overrides[get_task_queue] = lambda: FakeQueue()
    client = TestClient(app)
    token = create_access_token(user_id=user.id, role=user.role).token
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _task(status="failed"):  # noqa: ANN001
    from app.models.agent_task import AgentTask

    task = AgentTask(
        user_id=18, task_type="weekly_mindmap", input_json={"days": 30}, status=status
    )
    task.id = 11
    task.created_at = datetime(2026, 11, 17, tzinfo=timezone.utc)
    task.steps_count = 11
    task.token_cost = 0
    task.error = "old"
    task.started_at = None
    task.finished_at = None
    task.result_json = None
    return task


def test_retry_returns_202(monkeypatch):
    monkeypatch.setattr(
        agent_service, "retry_agent_task", lambda *a, **k: _task("pending")
    )
    resp = _client(_user()).post("/api/v1/agent/tasks/11/retry")
    assert resp.status_code == 202
    assert resp.json()["data"]["status"] == "pending"


def test_retry_conflict_409(monkeypatch):
    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise ConflictError("只有失败任务可以重跑")

    monkeypatch.setattr(agent_service, "retry_agent_task", boom)
    resp = _client(_user()).post("/api/v1/agent/tasks/11/retry")
    assert resp.status_code == 409
    assert resp.json()["code"] == 40900


def test_retry_teacher_forbidden():
    resp = _client(_user("teacher")).post("/api/v1/agent/tasks/11/retry")
    assert resp.status_code == 403