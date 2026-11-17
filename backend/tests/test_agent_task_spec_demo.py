"""S6-2 demo 任务类型：输入校验、计划与收尾。"""
from __future__ import annotations

import pytest

from app.ai.agents.tasks.demo import DemoTaskSpec
from app.core.exceptions import InvalidParamError


def test_demo_rejects_unknown_tool_and_empty_steps():
    with pytest.raises(InvalidParamError):
        DemoTaskSpec.validate_input({"steps": []})
    with pytest.raises(InvalidParamError):
        DemoTaskSpec.validate_input({"steps": [{"tool": "nope", "input": {}}]})


def test_demo_requires_confirm_and_plan():
    data = DemoTaskSpec.validate_input(
        {
            "steps": [{"tool": "calculator", "input": {"expression": "1+1"}}],
            "require_confirm": True,
        }
    )
    spec = DemoTaskSpec(data)
    assert spec.requires_confirm is True
    plan = spec.build_plan({})
    assert plan[0]["tool"] == "calculator"
    assert plan[0]["purpose"] == "调用 calculator"


def test_demo_finalize_carries_artifacts_and_citations():
    spec = DemoTaskSpec({"steps": [{"tool": "calculator", "input": {}}]})
    result = spec.finalize(
        {"plan": [{"tool": "calculator"}], "artifacts": {"step_1": {}}, "citations": []}
    )
    assert result["summary"] == "完成 1 步"
    assert result["artifacts"] == {"step_1": {}}
    assert result["citations"] == []

def test_demo_validates_task_timeout_seconds():
    data = DemoTaskSpec.validate_input(
        {"steps": [{"tool": "calculator", "input": {"expression": "1+1"}}],
         "task_timeout_seconds": 1}
    )
    assert data["task_timeout_seconds"] == 1
    with pytest.raises(InvalidParamError):
        DemoTaskSpec.validate_input(
            {"steps": [{"tool": "calculator", "input": {"expression": "1+1"}}],
             "task_timeout_seconds": 0}
        )
