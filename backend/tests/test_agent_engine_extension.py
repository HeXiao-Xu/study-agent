"""S6-3 引擎动态规划：observe 后追加步骤、token 累加、步数上限。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.agents.engine import (
    AgentEngine,
    AgentStepLimitError,
    PlanExtension,
    RunContext,
)
from app.ai.agents.state import new_state


class Recorder:
    def __init__(self):  # noqa: ANN001
        self.steps = []

    def record(
        self,
        *,
        step_no,
        thought,
        status,
        state,
        tool_name=None,
        tool_input=None,
        tool_output=None,
        latency_ms=None,
    ):  # noqa: ANN001
        self.steps.append(
            {
                "step_no": step_no,
                "thought": thought,
                "status": status,
                "tool_name": tool_name,
                "tool_output": tool_output,
            }
        )


class SequenceSpec:
    task_type = "seq"
    requires_confirm = False

    def __init__(self, *, total=2, token_cost=0):  # noqa: ANN001
        self.total = total
        self.token_cost = token_cost

    def build_plan(self, state):  # noqa: ANN001
        return [{"tool": "calculator", "input": {"expression": "1+1"}, "purpose": "第一步"}]

    def extend_plan(self, state):  # noqa: ANN001
        done = len([s for s in state.get("plan") or [] if s["tool"] == "calculator"])
        if done < self.total:
            return PlanExtension(
                steps=[
                    {
                        "tool": "calculator",
                        "input": {"expression": "2+2"},
                        "purpose": f"第{done + 1}步",
                    }
                ],
                token_cost=self.token_cost,
                thought="追加下一步",
            )
        return PlanExtension()

    def finalize(self, state):  # noqa: ANN001
        return {"summary": "ok", "artifacts": state.get("artifacts") or {}}


def _run(spec, *, max_steps=12, state=None):  # noqa: ANN001
    recorder = Recorder()
    engine = AgentEngine(
        spec,
        RunContext(
            user=SimpleNamespace(id=50),
            recorder=recorder,
            tool_invoker=lambda name, ctx, payload: {"echo": payload},
        ),
    )
    initial = state or new_state(
        user_id=50, task_input={}, token_budget=20000, max_steps=max_steps
    )
    final = engine.run(initial)
    return final, recorder


def test_extend_plan_appends_steps_and_accumulates_tokens():
    final, recorder = _run(SequenceSpec(total=3, token_cost=7))
    assert final["status"] == "succeeded"
    assert len([s for s in recorder.steps if s["tool_name"] == "calculator"]) == 3
    assert final["token_cost"] == 14
    assert any("追加下一步" in (s["thought"] or "") for s in recorder.steps)


def test_extend_plan_can_stop():
    final, recorder = _run(SequenceSpec(total=1))
    assert final["status"] == "succeeded"
    assert len([s for s in recorder.steps if s["tool_name"] == "calculator"]) == 1


def test_extended_steps_respect_max_steps():
    with pytest.raises(AgentStepLimitError):
        _run(SequenceSpec(total=10), max_steps=4)