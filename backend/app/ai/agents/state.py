"""S6-2 Agent 图状态：TypedDict 定义与 JSON 化。"""
from __future__ import annotations

import json
from typing import Any, TypedDict

STATUS_RUNNING = "running"
STATUS_WAITING_CONFIRM = "waiting_confirm"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"


class PlanStep(TypedDict):
    tool: str
    input: dict[str, Any]
    purpose: str


class AgentState(TypedDict, total=False):
    """LangGraph 的共享状态；字段与 spec §5.1 一致。"""

    user_id: int
    task_input: dict[str, Any]
    plan: list[dict[str, Any]]
    current_index: int
    artifacts: dict[str, Any]
    citations: list[dict[str, Any]]
    need_human_confirm: bool
    confirm_decision: dict[str, Any] | None
    retry_count: int
    token_budget: int
    token_cost: int
    max_steps: int
    step_count: int
    last_error: str | None
    fatal_error: str | None
    status: str
    resume_from: str | None
    result: dict[str, Any] | None
    last_output: dict[str, Any] | None
    error: str | None


def new_state(
    *,
    user_id: int,
    task_input: dict[str, Any],
    token_budget: int,
    max_steps: int,
) -> AgentState:
    return AgentState(
        user_id=user_id,
        task_input=task_input,
        plan=[],
        current_index=0,
        artifacts={},
        citations=[],
        need_human_confirm=False,
        confirm_decision=None,
        retry_count=0,
        token_budget=token_budget,
        token_cost=0,
        max_steps=max_steps,
        step_count=0,
        last_error=None,
        fatal_error=None,
        status=STATUS_RUNNING,
        resume_from=None,
        result=None,
        last_output=None,
        error=None,
    )


def jsonable(value: Any) -> Any:
    """把状态/工具出参转成可写 JSONB 的结构。

    工具出参已经过 `model_dump(mode="json")`；这里兜底 datetime/Decimal 等。
    """
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))