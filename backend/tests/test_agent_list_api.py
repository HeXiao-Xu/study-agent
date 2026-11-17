"""S6-5 Agent 任务列表：筛选、分页、权限。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.schemas.common import PageData
from app.services import agent_service


class FakeSession:
    def __init__(self, user):  # noqa: ANN001
        self.user = user

    def scalar(self, statement):  # noqa: ANN001, ANN201
        return self.user


def _user(role="student"):  # noqa: ANN001
    user = User(
        username="agent_s65",
        nickname="a",
        grade="高二",
        role=role,
        password_hash="x",
    )
    user.id = 50
    return user


def _client(user):  # noqa: ANN001
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    client = TestClient(app)
    token = create_access_token(user_id=user.id, role=user.role).token
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _task(task_id=7, status="succeeded"):  # noqa: ANN001
    from app.models.agent_task import AgentTask

    task = AgentTask(user_id=50, task_type="weekly_mindmap", input_json={}, status=status)
    task.id = task_id
    task.created_at = datetime(2026, 11, 17, tzinfo=timezone.utc)
    task.steps_count = 4
    task.token_cost = 0
    task.error = None
    task.started_at = None
    task.finished_at = None
    task.result_json = None
    return task


def test_list_returns_page_and_passes_filters(monkeypatch):
    captured = {}

    def fake_list(session, *, user_id, status, task_type, page, sort):  # noqa: ANN001
        captured.update(
            user_id=user_id, status=status, task_type=task_type, page=page, sort=sort
        )
        return PageData(items=[], total=0, page=page.page, page_size=page.page_size)

    monkeypatch.setattr(agent_service, "list_agent_tasks", fake_list)
    resp = _client(_user()).get(
        "/api/v1/agent/tasks",
        params={"status": "failed", "task_type": "weekly_mindmap", "page_size": 2},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["page_size"] == 2
    assert captured["user_id"] == 50
    assert captured["status"] == "failed"
    assert captured["task_type"] == "weekly_mindmap"


def test_list_returns_items(monkeypatch):
    monkeypatch.setattr(
        agent_service,
        "list_agent_tasks",
        lambda *a, **k: PageData(
            items=[agent_service.AgentTaskOut.model_validate(_task())],
            total=1,
            page=1,
            page_size=10,
        ),
    )
    data = _client(_user()).get("/api/v1/agent/tasks").json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["task_type"] == "weekly_mindmap"


def test_list_rejects_bad_status():
    resp = _client(_user()).get("/api/v1/agent/tasks", params={"status": "nope"})
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_list_teacher_forbidden():
    resp = _client(_user("teacher")).get("/api/v1/agent/tasks")
    assert resp.status_code == 403