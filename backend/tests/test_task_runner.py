"""S2-7 执行器：状态机、重试退避、幂等（假 session，不连库）。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.async_task import AsyncTask
from app.tasks import registry, runner


class FakeSession:
    def __init__(self, task: AsyncTask | None) -> None:
        self.task = task
        self.commits = 0
        self.rollbacks = 0

    def get(self, entity: type, pk: int):
        return self.task

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeSessionCtx:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.closed = False

    def __enter__(self) -> FakeSession:
        return self.session

    def __exit__(self, *exc_info: object) -> None:
        self.closed = True


def _task(*, status: str = "pending", name: str = "demo.sleep") -> AsyncTask:
    task = AsyncTask(
        user_id=1,
        name=name,
        status=status,
        payload={"seconds": 0},
        attempts=0,
    )
    task.id = 5
    return task


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    ctx = FakeSessionCtx(FakeSession(_task()))
    monkeypatch.setattr(runner, "new_session", lambda: ctx)
    monkeypatch.setattr(runner, "get_handler", lambda name: registry.get_handler(name))
    monkeypatch.setattr(
        runner,
        "get_settings",
        lambda: SimpleNamespace(task_max_tries=3, task_retry_base_seconds=2.0),
    )
    return ctx.session


def test_execute_success_sets_terminal_fields(session: FakeSession) -> None:
    outcome = runner.execute_task(5, 1)
    assert outcome.status == "succeeded"
    assert outcome.retry_in is None
    task = session.task
    assert task is not None
    assert task.status == "succeeded"
    assert task.attempts == 1
    assert task.started_at is not None
    assert task.finished_at is not None
    assert task.result == {"slept": 0}


def test_execute_terminal_task_skips_handler(
    session: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert session.task is not None
    session.task.status = "succeeded"
    called: list[int] = []
    monkeypatch.setattr(runner, "get_handler", lambda name: called.append(1) or None)
    outcome = runner.execute_task(5, 1)
    assert outcome.status == "succeeded"
    assert called == []


def test_execute_missing_task_returns_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = FakeSessionCtx(FakeSession(None))
    monkeypatch.setattr(runner, "new_session", lambda: ctx)
    assert runner.execute_task(99, 1).status == "missing"


def test_execute_unknown_name_fails(session: FakeSession) -> None:
    assert session.task is not None
    session.task.name = "no.such.task"
    outcome = runner.execute_task(5, 1)
    assert outcome.status == "failed"
    assert "未知任务类型" in (session.task.error or "")


def test_execute_first_failure_returns_to_pending_with_delay(
    session: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(session_, payload):  # noqa: ANN001
        raise RuntimeError("第一次炸")

    monkeypatch.setattr(runner, "get_handler", lambda name: boom)
    outcome = runner.execute_task(5, 1)
    assert outcome.status == "pending"
    assert outcome.retry_in == 2.0
    assert session.task is not None
    assert session.task.attempts == 1
    assert "第 1 次失败" in (session.task.error or "")
    assert session.task.finished_at is None


def test_execute_second_failure_doubles_delay(
    session: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(session_, payload):  # noqa: ANN001
        raise RuntimeError("第二次炸")

    monkeypatch.setattr(runner, "get_handler", lambda name: boom)
    assert runner.execute_task(5, 2).retry_in == 4.0


def test_execute_last_attempt_marks_failed(
    session: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(session_, payload):  # noqa: ANN001
        raise RuntimeError("最后一次炸")

    monkeypatch.setattr(runner, "get_handler", lambda name: boom)
    outcome = runner.execute_task(5, 3)
    assert outcome.status == "failed"
    assert outcome.retry_in is None
    assert session.task is not None
    assert session.task.status == "failed"
    assert session.task.attempts == 3
    assert session.task.finished_at is not None
    assert "第 3 次失败" in (session.task.error or "")


def test_execute_success_clears_previous_error(session: FakeSession) -> None:
    assert session.task is not None
    session.task.error = "上次失败"
    runner.execute_task(5, 1)
    assert session.task.error is None