"""S6-1 工具注册表：基座契约与登记顺序。"""
from __future__ import annotations

import dataclasses

import pytest

from app.ai.agents.tools.base import (
    ToolContext,
    ToolExecutionError,
    ToolInputError,
    invoke_tool,
)
from app.ai.agents.tools.registry import TOOL_ORDER, TOOLS


class _FakeSession:
    pass


class _User:
    id = 50
    role = "student"


def _ctx() -> ToolContext:
    return ToolContext(session=_FakeSession(), user=_User())  # type: ignore[arg-type]


def test_registry_starts_with_two_pure_tools():
    assert TOOL_ORDER == ["make_mindmap", "calculator"]
    assert set(TOOLS) == set(TOOL_ORDER)


def test_invoke_unknown_tool_raises_404():
    from app.core.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        invoke_tool("nope", _ctx(), {})


def test_invoke_invalid_input_raises_422():
    with pytest.raises(ToolInputError):
        invoke_tool("calculator", _ctx(), {"expression": ""})


def test_invoke_wraps_unexpected_error():
    spec = TOOLS["calculator"]
    TOOLS["calculator"] = dataclasses.replace(
        spec, handler=lambda ctx, data: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    try:
        with pytest.raises(ToolExecutionError):
            invoke_tool("calculator", _ctx(), {"expression": "1+1"})
    finally:
        TOOLS["calculator"] = spec


def test_invoke_returns_output_model():
    out = invoke_tool("calculator", _ctx(), {"expression": "2+2"})
    assert out.value == 4
    assert out.exact is True