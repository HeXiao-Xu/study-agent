"""S3-7 调用日志写入口：字段、Decimal 与失败不抛。"""
from __future__ import annotations

from decimal import Decimal

from app.core import llm_log
from app.core.context import reset_current_user_id, set_current_user_id
from app.models.llm_call_log import LLMCallLog


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False
        self.closed = False

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_record_llm_call_writes_success_row() -> None:
    session = FakeSession()
    token = set_current_user_id(18)
    try:
        llm_log.record_llm_call(
            scene="qa",
            model="qwen-plus",
            status="success",
            prompt_tokens=100,
            completion_tokens=20,
            cost_yuan=0.00012,
            latency_ms=321,
            session_factory=lambda: session,
        )
    finally:
        reset_current_user_id(token)

    row = session.added[0]
    assert isinstance(row, LLMCallLog)
    assert row.user_id == 18
    assert row.scene == "qa"
    assert row.status == "success"
    assert row.cost == Decimal("0.00012")
    assert row.trace_id is None
    assert session.committed is True
    assert session.closed is True


def test_record_llm_call_failure_does_not_raise() -> None:
    class Boom:
        def add(self, instance: object) -> None:
            raise RuntimeError("db down")

        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    llm_log.record_llm_call(
        scene="qa",
        model="m",
        status="failed",
        prompt_tokens=None,
        completion_tokens=None,
        cost_yuan=None,
        latency_ms=1,
        session_factory=lambda: Boom(),
    )