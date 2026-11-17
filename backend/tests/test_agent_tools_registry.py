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


def test_registry_has_eleven_tools_in_scheme_order():
    assert TOOL_ORDER == [
        "search_notes",
        "list_notes",
        "get_kp_subgraph",
        "list_mistakes",
        "get_mastery",
        "search_questions",
        "generate_questions",
        "make_mindmap",
        "create_review_plan",
        "export_paper_pdf",
        "calculator",
    ]
    assert set(TOOLS) == set(TOOL_ORDER)
    assert all(spec.write is False for spec in TOOLS.values())


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

def test_invalid_tool_input_does_not_call_handler():
    spec = TOOLS["calculator"]
    called = {"n": 0}
    original = spec.handler

    def spy(ctx, data):  # noqa: ANN001
        called["n"] += 1
        return original(ctx, data)

    TOOLS["calculator"] = dataclasses.replace(spec, handler=spy)
    try:
        with pytest.raises(ToolInputError):
            invoke_tool("calculator", _ctx(), {"expression": ""})
        assert called["n"] == 0
    finally:
        TOOLS["calculator"] = spec


def test_write_tool_requires_allow_write():
    from app.ai.agents.tools.base import ToolContext, ToolSpec
    from app.ai.agents.tools.calculator import CalculatorIn, CalculatorOut
    from app.core.exceptions import ForbiddenError

    called = {"n": 0}

    def handler(ctx, data):  # noqa: ANN001
        called["n"] += 1
        return CalculatorOut(expression="1", value=1, text="1", exact=True)

    TOOLS["fake_write"] = ToolSpec(
        name="fake_write",
        description="写入测试",
        input_model=CalculatorIn,
        output_model=CalculatorOut,
        handler=handler,
        write=True,
    )
    try:
        with pytest.raises(ForbiddenError):
            invoke_tool("fake_write", _ctx(), {"expression": "1"})
        assert called["n"] == 0

        allowed = ToolContext(
            session=_FakeSession(), user=_User(), allow_write=True
        )  # type: ignore[arg-type]
        out = invoke_tool("fake_write", allowed, {"expression": "1"})
        assert out.value == 1
        assert called["n"] == 1
    finally:
        TOOLS.pop("fake_write", None)
