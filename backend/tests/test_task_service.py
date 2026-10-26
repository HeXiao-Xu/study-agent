"""S2-7 任务服务：假 session + 假队列，不连库不连 Redis。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.exceptions import (
    ForbiddenError,
    InvalidParamError,
    NotFoundError,
    TaskQueueUnavailableError,
)
from app.models.async_task import AsyncTask
from app.models.user import User
from app.services import task_service


class FakeSession:
    def __init__(self) -> None:
        self.rows: dict[int, AsyncTask] = {}
        self.added: list[AsyncTask] = []
        self.commits = 0
        self.refreshed: list[AsyncTask] = []

    def add(self, instance: AsyncTask) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1
        for row in self.added:
            if row.id is None:
                row.id = 21
            row.created_at = datetime.now(timezone.utc)
            self.rows[row.id] = row

    def refresh(self, instance: AsyncTask) -> None:
        self.refreshed.append(instance)
        if instance.id is None:
            instance.id = 21
        if instance.created_at is None:
            instance.created_at = datetime.now(timezone.utc)

    def get(self, entity: type, pk: int):
        return self.rows.get(pk) if entity is AsyncTask else None


class FakeQueue:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def enqueue(self, name: str, task_id: int) -> None:
        self.calls.append((name, task_id))
        if self.error is not None:
            raise self.error


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


def test_create_task_unknown_name_raises_422() -> None:
    with pytest.raises(InvalidParamError):
        task_service.create_task(
            FakeSession(),
            owner=_user(),
            name="no.such.task",
            payload={},
            queue=FakeQueue(),
        )


def test_create_task_persists_pending_and_enqueues() -> None:
    session, queue = FakeSession(), FakeQueue()
    task = task_service.create_task(
        session,
        owner=_user(),
        name="demo.sleep",
        payload={"seconds": 0},
        queue=queue,
    )
    assert task.id == 21
    assert task.status == "pending"
    assert task.user_id == 1
    assert queue.calls == [("demo.sleep", 21)]
    assert session.commits == 1


def test_create_task_enqueue_failure_marks_failed_and_raises() -> None:
    session = FakeSession()
    with pytest.raises(TaskQueueUnavailableError):
        task_service.create_task(
            session,
            owner=_user(),
            name="demo.sleep",
            payload={"seconds": 0},
            queue=FakeQueue(error=OSError("redis down")),
        )
    row = session.added[0]
    assert row.status == "failed"
    assert row.error == "任务入队失败"
    assert row.finished_at is not None
    assert session.commits == 2


def test_submit_demo_defaults_to_five_seconds() -> None:
    task = task_service.submit_demo(
        FakeSession(), owner=_user(), seconds=5, fail=False, queue=FakeQueue()
    )
    assert task.name == "demo.sleep"
    assert task.payload == {"seconds": 5, "fail": False}


def test_get_task_returns_own_task() -> None:
    session = FakeSession()
    task = task_service.submit_demo(
        session, owner=_user(), seconds=1, fail=False, queue=FakeQueue()
    )
    assert task_service.get_task(session, task_id=21, viewer=_user(1)) is task


def test_get_task_other_user_raises_403() -> None:
    session = FakeSession()
    task_service.submit_demo(
        session, owner=_user(1), seconds=1, fail=False, queue=FakeQueue()
    )
    with pytest.raises(ForbiddenError):
        task_service.get_task(session, task_id=21, viewer=_user(2))


def test_get_task_missing_raises_404() -> None:
    with pytest.raises(NotFoundError):
        task_service.get_task(FakeSession(), task_id=99, viewer=_user())


def test_demo_task_name_matches_registry() -> None:
    from app.tasks.registry import get_handler

    assert get_handler(task_service.TASK_DEMO_SLEEP) is not None