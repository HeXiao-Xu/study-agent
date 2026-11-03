"""S4-4 变式任务：注册名、参数透传、不 commit。"""
from __future__ import annotations

from app.tasks import generate_variants as task_module
from app.tasks.registry import get_handler


class FakeSession:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def test_variant_task_registered():
    assert get_handler("mistake.variants") is task_module.run_generate_variants


def test_variant_task_delegates_and_does_not_commit(monkeypatch):
    calls: dict = {}

    def _fake(session, *, user_id, mistake_id):
        calls.update(user_id=user_id, mistake_id=mistake_id)
        return {"mistake_id": mistake_id, "passed": 2}

    monkeypatch.setattr(task_module.question_gen_service, "run_generation", _fake)
    session = FakeSession()

    result = task_module.run_generate_variants(session, {"user_id": 5, "mistake_id": 43})

    assert result["passed"] == 2
    assert calls == {"user_id": 5, "mistake_id": 43}
    assert session.commits == 0