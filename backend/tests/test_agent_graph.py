"""S6-2 图引擎：3 步成功、重试、预算、步数、挂起/恢复。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.agents.engine import AgentEngine, AgentStepLimitError, RunContext
from app.ai.agents.state import new_state
from app.ai.agents.tasks.demo import DemoTaskSpec
from app.core.exceptions import InvalidParamError


class MemoryRecorder:
    def __init__(self) -> None:
        self.steps: list[dict] = []
        self.states: list[dict] = []

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
                "tool_input": tool_input,
                "tool_output": tool_output,
                "latency_ms": latency_ms,
            }
        )
        self.states.append(dict(state))


def _ctx(recorder, invoker):  # noqa: ANN001
    return RunContext(
        user=SimpleNamespace(id=50), recorder=recorder, tool_invoker=invoker, session=None
    )


def _state(steps, *, budget=20000, max_steps=12, confirm=False):  # noqa: ANN001
    spec = DemoTaskSpec({"steps": steps, "require_confirm": confirm})
    state = new_state(
        user_id=50,
        task_input={"steps": steps, "require_confirm": confirm},
        token_budget=budget,
        max_steps=max_steps,
    )
    return spec, state


def _echo(name, ctx, payload):  # noqa: ANN001
    return {"tool": name, "payload": payload}


def test_three_step_demo_succeeds_with_complete_steps():
    recorder = MemoryRecorder()
    steps = [
        {"tool": "calculator", "input": {"expression": "1+1"}, "purpose": "算 1+1"},
        {"tool": "calculator", "input": {"expression": "2+2"}, "purpose": "算 2+2"},
        {"tool": "make_mindmap", "input": {"title": "函数"}, "purpose": "画导图"},
    ]
    spec, state = _state(steps)
    final = AgentEngine(spec, _ctx(recorder, _echo)).run(state)
    assert final["status"] == "succeeded"
    assert final["result"]["summary"] == "完成 3 步"
    assert [s["tool_name"] for s in recorder.steps if s["tool_name"]] == [
        "calculator",
        "calculator",
        "make_mindmap",
    ]
    assert len(recorder.steps) == 8  # plan + act/observe*3 + finalize
    act_rows = [s for s in recorder.steps if s["tool_name"]]
    assert act_rows[0]["tool_input"] == {"expression": "1+1"}
    assert act_rows[0]["tool_output"]["payload"] == {"expression": "1+1"}
    assert act_rows[0]["latency_ms"] is not None
    assert final["artifacts"]["step_1"]["tool"] == "calculator"
    assert recorder.steps[0]["thought"].startswith("计划 3 步")


def test_tool_failure_retries_twice_then_succeeds():
    recorder = MemoryRecorder()
    calls = {"n": 0}

    def flaky(name, ctx, payload):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] < 3:
            raise InvalidParamError("工具临时失败")
        return {"ok": True}

    spec, state = _state([{"tool": "calculator", "input": {}}])
    final = AgentEngine(spec, _ctx(recorder, flaky)).run(state)
    assert final["status"] == "succeeded"
    assert [s["status"] for s in recorder.steps].count("error") == 4
    assert any("重试" in (s["thought"] or "") for s in recorder.steps)


def test_tool_failure_exhausts_retries():
    recorder = MemoryRecorder()

    def boom(name, ctx, payload):  # noqa: ANN001
        raise RuntimeError("boom")

    spec, state = _state([{"tool": "calculator", "input": {}}])
    final = AgentEngine(spec, _ctx(recorder, boom)).run(state)
    assert final["status"] == "failed"
    assert "重试" in final["error"]


def test_token_budget_exceeded_stops_before_tools():
    recorder = MemoryRecorder()
    spec, state = _state([{"tool": "calculator", "input": {}}], budget=100)
    state["token_cost"] = 100
    final = AgentEngine(spec, _ctx(recorder, _echo)).run(state)
    assert final["status"] == "failed"
    assert "token 预算" in final["error"]
    assert [s["tool_name"] for s in recorder.steps if s["tool_name"]] == []


def test_max_steps_raises_limit_error():
    recorder = MemoryRecorder()
    spec, state = _state(
        [{"tool": "calculator", "input": {}}, {"tool": "calculator", "input": {}}],
        max_steps=2,
    )
    with pytest.raises(AgentStepLimitError):
        AgentEngine(spec, _ctx(recorder, _echo)).run(state)


def test_confirm_suspends_then_resume_approves():
    recorder = MemoryRecorder()
    steps = [{"tool": "calculator", "input": {"expression": "1+1"}}]
    spec, state = _state(steps, confirm=True)
    suspended = AgentEngine(spec, _ctx(recorder, _echo)).run(state)
    assert suspended["status"] == "waiting_confirm"
    assert recorder.steps[-1]["status"] == "waiting_confirm"
    assert len([s for s in recorder.steps if s["tool_name"]]) == 1

    suspended["confirm_decision"] = {"approved": True, "comment": None, "edits": None}
    suspended["resume_from"] = "confirm"
    suspended["status"] = "running"
    final = AgentEngine(spec, _ctx(recorder, _echo)).run(suspended)
    assert final["status"] == "succeeded"
    assert recorder.steps[-1]["thought"] == "任务完成"
    assert len([s for s in recorder.steps if s["tool_name"]]) == 1  # 不重跑工具


def test_confirm_reject_fails():
    recorder = MemoryRecorder()
    spec, state = _state([{"tool": "calculator", "input": {}}], confirm=True)
    suspended = AgentEngine(spec, _ctx(recorder, _echo)).run(state)
    suspended["confirm_decision"] = {"approved": False, "comment": None, "edits": None}
    suspended["resume_from"] = "confirm"
    suspended["status"] = "running"
    final = AgentEngine(spec, _ctx(recorder, _echo)).run(suspended)
    assert final["status"] == "failed"
    assert final["error"] == "用户拒绝确认"