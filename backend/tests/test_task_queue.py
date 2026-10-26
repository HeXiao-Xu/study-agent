"""S2-7 ARQ 队列适配器：假 pool，不连 Redis。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.exceptions import TaskQueueUnavailableError
from app.tasks import queue as queue_module


class FakeJob:
    job_id = "task:9"


class FakePool:
    def __init__(self, *, result: FakeJob | None = None, error: Exception | None = None):
        self.result = result if result is not None else FakeJob()
        self.error = error
        self.calls: list[dict[str, object]] = []
        self.closed = False

    async def enqueue_job(self, function, *args, **kwargs):  # noqa: ANN001
        self.calls.append({"function": function, "args": args, **kwargs})
        if self.error is not None:
            raise self.error
        return self.result

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def pool(monkeypatch: pytest.MonkeyPatch) -> FakePool:
    fake = FakePool()

    async def fake_create_pool(settings_=None):  # noqa: ANN001
        return fake

    monkeypatch.setattr(queue_module, "create_pool", fake_create_pool)
    monkeypatch.setattr(
        queue_module,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://127.0.0.1:6379/0",
            task_job_timeout_seconds=300,
            task_max_tries=3,
        ),
    )
    return fake


def test_enqueue_passes_task_id_and_fixed_job_id(pool: FakePool) -> None:
    queue_module.ArqTaskQueue().enqueue("demo.sleep", 9)
    call = pool.calls[0]
    assert call["function"] == "run_task"
    assert call["args"] == (9,)
    assert call["_job_id"] == "task:9"


def test_enqueue_does_not_pass_worker_settings_as_kwargs(pool: FakePool) -> None:
    queue_module.ArqTaskQueue().enqueue("demo.sleep", 9)
    assert set(pool.calls[0]) == {"function", "args", "_job_id"}


def test_enqueue_closes_pool(pool: FakePool) -> None:
    queue_module.ArqTaskQueue().enqueue("demo.sleep", 9)
    assert pool.closed is True


def test_enqueue_none_job_raises(pool: FakePool) -> None:
    pool.result = None
    with pytest.raises(TaskQueueUnavailableError):
        queue_module.ArqTaskQueue().enqueue("demo.sleep", 9)


def test_enqueue_redis_error_is_wrapped(pool: FakePool) -> None:
    pool.error = OSError("connection refused")
    with pytest.raises(TaskQueueUnavailableError) as excinfo:
        queue_module.ArqTaskQueue().enqueue("demo.sleep", 9)
    assert "redis" not in excinfo.value.message.lower()
    assert pool.closed is True