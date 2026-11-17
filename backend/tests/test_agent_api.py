"""S6-2 Agent API：202/200、权限、409/422、Envelope。"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.exceptions import ConflictError
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
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
    user = User(
        username="agent_s62",
        nickname="agent",
        grade="高二",
        role=role,
        password_hash="x",
    )
    user.id = 50
    return user


def _client(user):  # noqa: ANN001
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    app.dependency_overrides[get_task_queue] = lambda: FakeQueue()
    client = TestClient(app)
    token = create_access_token(user_id=user.id, role=user.role).token
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _task(status="pending"):  # noqa: ANN001
    from app.models.agent_task import AgentTask

    task = AgentTask(
        user_id=50,
        task_type="demo",
        input_json={"steps": [{"tool": "calculator", "input": {"expression": "1+1"}}]},
        status=status,
    )
    task.id = 71
    task.created_at = datetime(2026, 11, 17, tzinfo=timezone.utc)
    task.steps_count = 0
    task.token_cost = 0
    task.started_at = None
    task.finished_at = None
    task.error = None
    task.result_json = None
    return task


def _step(step_no=1):  # noqa: ANN001
    return SimpleNamespace(
        step_no=step_no,
        thought="计划 1 步",
        tool_name=None,
        tool_input_json=None,
        tool_output_json=None,
        latency_ms=None,
        status="ok",
    )


def test_create_returns_202(monkeypatch):
    monkeypatch.setattr(agent_service, "create_agent_task", lambda *a, **k: _task())
    resp = _client(_user()).post(
        "/api/v1/agent/tasks",
        json={
            "task_type": "demo",
            "input": {"steps": [{"tool": "calculator", "input": {"expression": "1+1"}}]},
        },
    )
    assert resp.status_code == 202
    assert resp.json()["data"]["status"] == "pending"


def test_get_detail_returns_steps(monkeypatch):
    task = _task("waiting_confirm")
    task.result_json = {"awaiting_confirm": True, "artifacts": {}, "citations": []}
    monkeypatch.setattr(
        agent_service, "get_agent_task", lambda *a, **k: (task, [_step(1), _step(2)])
    )
    resp = _client(_user()).get("/api/v1/agent/tasks/71")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "waiting_confirm"
    assert [item["step_no"] for item in data["steps"]] == [1, 2]


def test_confirm_returns_202(monkeypatch):
    monkeypatch.setattr(
        agent_service, "confirm_agent_task", lambda *a, **k: _task("pending")
    )
    resp = _client(_user()).post(
        "/api/v1/agent/tasks/71/confirm", json={"approved": True, "comment": "可以"}
    )
    assert resp.status_code == 202


def test_confirm_conflict_409(monkeypatch):
    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise ConflictError("当前状态不需要确认")

    monkeypatch.setattr(agent_service, "confirm_agent_task", boom)
    resp = _client(_user()).post("/api/v1/agent/tasks/71/confirm", json={"approved": True})
    assert resp.status_code == 409
    assert resp.json()["code"] == 40900


def test_teacher_forbidden():
    resp = _client(_user("teacher")).post(
        "/api/v1/agent/tasks", json={"task_type": "demo", "input": {"steps": []}}
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_invalid_payload_422():
    resp = _client(_user()).post("/api/v1/agent/tasks", json={"task_type": "demo"})
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200