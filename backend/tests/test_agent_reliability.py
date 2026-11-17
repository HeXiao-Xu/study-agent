"""S6-6 可靠性：超时、工具超时、预算/限步保留产物、日志。"""
from __future__ import annotations

import logging
import time
from types import SimpleNamespace

import pytest

from app.ai.agents.engine import (
    AgentEngine,
    AgentStepLimitError,
    AgentTaskTimeoutError,
    PlanExtension,
    RunContext,
)
from app.ai.agents.state import new_state


class Recorder:
    def __init__(self):  # noqa: ANN001
        self.steps = []

    def record(self, *, step_no, thought, status, state, **kwargs):  # noqa: ANN001
        self.steps.append(step_no)


class OneStepSpec:
    task_type = "one"
    requires_confirm = False

    def build_plan(self, state):  # noqa: ANN001
        return [{"tool": "calculator", "input": {}, "purpose": "一步"}]

    def extend_plan(self, state):  # noqa: ANN001
        return PlanExtension()

    def finalize(self, state):  # noqa: ANN001
        return {"artifacts": state.get("artifacts") or {}}


def _engine(spec, invoker):  # noqa: ANN001
    return AgentEngine(
        spec,
        RunContext(
            user=SimpleNamespace(id=18),
            recorder=Recorder(),
            tool_invoker=invoker,
        ),
    )


def test_deadline_in_past_raises_timeout(caplog):
    state = new_state(user_id=18, task_input={}, token_budget=20000, max_steps=12)
    state["deadline_at"] = time.time() - 1
    state["step_count"] = 1
    with caplog.at_level(logging.WARNING):
        with pytest.raises(AgentTaskTimeoutError):
            _engine(OneStepSpec(), lambda *a, **k: {}).run(state)
    assert "agent_task_timeout" in caplog.text


def test_tool_timeout_error_is_retried_then_fails(caplog):
    calls = {"n": 0}

    def boom(*a, **k):  # noqa: ANN002, ANN003
        calls["n"] += 1
        raise TimeoutError("slow")

    state = new_state(user_id=18, task_input={}, token_budget=20000, max_steps=12)
    with caplog.at_level(logging.WARNING):
        final = _engine(OneStepSpec(), boom).run(state)
    assert final["status"] == "failed"
    assert "重试" in final["error"]
    assert calls["n"] == 3
    assert "agent_tool_timeout" in caplog.text


def test_budget_exhausted_keeps_artifacts_and_logs(caplog):
    state = new_state(user_id=18, task_input={}, token_budget=100, max_steps=12)
    state["token_cost"] = 100
    with caplog.at_level(logging.WARNING):
        final = _engine(OneStepSpec(), lambda *a, **k: {}).run(state)
    assert final["status"] == "failed"
    assert "token 预算" in final["error"]
    assert final["result"]["artifacts"] == {}
    assert "agent_budget_exhausted" in caplog.text


def test_step_limit_error_class_is_raised():
    state = new_state(user_id=18, task_input={}, token_budget=20000, max_steps=1)
    with pytest.raises(AgentStepLimitError):
        _engine(OneStepSpec(), lambda *a, **k: {}).run(state)