"""S6-2 Agent service：创建/查询/确认/入队失败与终态幂等。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.exceptions import ConflictError, ForbiddenError, InvalidParamError
from app.models.agent_task import AgentTask
from app.models.user import User
from app.services import agent_service


class FakeSession:
    def __init__(self, task=None, user=None):  # noqa: ANN001
        self.task = task
        self.user = user
        self.added = []
        self.commits = 0

    def add(self, obj):  # noqa: ANN001
        self.added.append(obj)

    def commit(self):  # noqa: ANN001
        self.commits += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = 71

    def refresh(self, obj):  # noqa: ANN001
        if getattr(obj, "id", None) is None:
            obj.id = 71

    def get(self, model, pk):  # noqa: ANN001, ANN201
        if model is AgentTask and self.task and self.task.id == pk:
            return self.task
        if model is User:
            return self.user
        return None


class FakeQueue:
    def __init__(self, fail=False):  # noqa: ANN001
        self.calls = []
        self.fail = fail

    def enqueue(self, name, task_id):  # noqa: ANN001
        if self.fail:
            raise RuntimeError("redis down")
        self.calls.append((name, task_id))


def _owner(user_id=50):  # noqa: ANN001
    return SimpleNamespace(id=user_id, role="student")


def _task(status="pending", *, owner_id=50, state=None):  # noqa: ANN001
    task = AgentTask(
        user_id=owner_id,
        task_type="demo",
        input_json={"steps": [{"tool": "calculator", "input": {"expression": "1+1"}}]},
        status=status,
        state_json=state,
    )
    task.id = 71
    return task


def test_create_unknown_type_raises_422(monkeypatch):
    monkeypatch.setattr(agent_service.task_service, "create_task", lambda *a, **k: None)
    with pytest.raises(InvalidParamError):
        agent_service.create_agent_task(
            FakeSession(), owner=_owner(), task_type="mistake_paper", task_input={}, queue=FakeQueue()
        )


def test_create_demo_enqueues(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        agent_service.task_service, "create_task", lambda *a, **k: captured.update(k)
    )
    session = FakeSession()
    task = agent_service.create_agent_task(
        session,
        owner=_owner(),
        task_type="demo",
        task_input={"steps": [{"tool": "calculator", "input": {"expression": "1+1"}}]},
        queue=FakeQueue(),
    )
    assert task.status == "pending"
    assert captured["name"] == agent_service.TASK_RUN_AGENT
    assert captured["payload"] == {"agent_task_id": 71}


def test_create_enqueue_failure_marks_failed(monkeypatch):
    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise RuntimeError("queue")

    monkeypatch.setattr(agent_service.task_service, "create_task", boom)
    task = _task()
    session = FakeSession(task)
    with pytest.raises(RuntimeError):
        agent_service.create_agent_task(
            session,
            owner=_owner(),
            task_type="demo",
            task_input={"steps": [{"tool": "calculator", "input": {"expression": "1+1"}}]},
            queue=FakeQueue(),
        )
    assert session.added[0].status == "failed"


def test_get_other_users_task_403():
    with pytest.raises(ForbiddenError):
        agent_service.get_agent_task(FakeSession(_task()), task_id=71, viewer=_owner(99))


def test_confirm_requires_waiting_status():
    with pytest.raises(ConflictError):
        agent_service.confirm_agent_task(
            FakeSession(_task("running")),
            task_id=71,
            viewer=_owner(),
            decision={"approved": True},
            queue=FakeQueue(),
        )


def test_confirm_writes_decision_and_requeues(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        agent_service.task_service, "create_task", lambda *a, **k: captured.update(k)
    )
    task = _task("waiting_confirm", state={"step_count": 9, "plan": [{"tool": "calculator"}]})
    agent_service.confirm_agent_task(
        FakeSession(task),
        task_id=71,
        viewer=_owner(),
        decision={"approved": True},
        queue=FakeQueue(),
    )
    assert task.status == "pending"
    assert task.state_json["resume_from"] == "confirm"
    assert task.state_json["confirm_decision"]["approved"] is True
    assert captured["payload"] == {"agent_task_id": 71}


def test_run_terminal_task_is_noop():
    task = _task("succeeded")
    assert agent_service.run_agent_task(FakeSession(task), 71) == {"status": "succeeded"}

def test_create_weekly_mindmap_allowed(monkeypatch):
    monkeypatch.setattr(agent_service.task_service, "create_task", lambda *a, **k: None)
    task = agent_service.create_agent_task(
        FakeSession(),
        owner=_owner(),
        task_type="weekly_mindmap",
        task_input={"days": 7},
        queue=FakeQueue(),
    )
    assert task.task_type == "weekly_mindmap"
    assert task.input_json["days"] == 7


def test_list_agent_tasks_scopes_user_and_sort(monkeypatch):
    from sqlalchemy.dialects import postgresql

    from app.schemas.common import PageData
    from app.utils.pagination import PageParams, SortParams

    captured = {}

    def fake_page(session, stmt, page, *, item_model):  # noqa: ANN001
        captured["sql"] = str(stmt.compile(dialect=postgresql.dialect()))
        captured["item_model"] = item_model
        return PageData(items=[], total=0, page=page.page, page_size=page.page_size)

    monkeypatch.setattr(agent_service, "paginate_query", fake_page)
    agent_service.list_agent_tasks(
        object(),
        user_id=50,
        status="running",
        task_type="demo",
        page=PageParams(page=2, page_size=5),
        sort=SortParams(),
    )
    sql = captured["sql"]
    assert "agent_tasks.user_id =" in sql
    assert "agent_tasks.status =" in sql
    assert "agent_tasks.task_type =" in sql
    assert "ORDER BY agent_tasks.created_at DESC" in sql
    assert "agent_tasks.id DESC" in sql
