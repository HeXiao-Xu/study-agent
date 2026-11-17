"""S6-2 `demo` 任务类型：把输入里的 3 步工具计划原样交给引擎。

只用于本卡验收；S6-3/S6-4 会新增 `weekly_mindmap` / `mistake_paper` 两个
`AgentTaskSpec` 实现，不需要改引擎与 API。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.agents.state import AgentState
from app.ai.agents.tools import TOOLS
from app.core.exceptions import InvalidParamError

MAX_STEPS = 5


class DemoStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1, max_length=64)
    input: dict[str, Any] = Field(default_factory=dict)
    purpose: str | None = Field(default=None, max_length=200)


class DemoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[DemoStep] = Field(min_length=1, max_length=MAX_STEPS)
    require_confirm: bool = False
    token_budget: int | None = Field(default=None, ge=100)


class DemoTaskSpec:
    task_type = "demo"

    def __init__(self, task_input: dict[str, Any]) -> None:
        self.task_input = task_input
        self.requires_confirm = bool(task_input.get("require_confirm"))

    @classmethod
    def validate_input(cls, raw: dict[str, Any]) -> dict[str, Any]:
        try:
            data = DemoInput.model_validate(raw)
        except ValidationError as exc:
            message = str(exc.errors()[0].get("msg", "任务输入不合法"))
            raise InvalidParamError(f"任务输入不合法：{message}") from exc
        for step in data.steps:
            spec = TOOLS.get(step.tool)
            if spec is None:
                raise InvalidParamError(f"未知工具：{step.tool}")
            try:
                spec.input_model.model_validate(step.input)
            except ValidationError as exc:
                message = str(exc.errors()[0].get("msg", "参数不合法"))
                raise InvalidParamError(
                    f"工具 {step.tool} 参数不合法：{message}"
                ) from exc
        return data.model_dump()

    def build_plan(self, state: AgentState) -> list[dict[str, Any]]:
        return [
            {
                "tool": step["tool"],
                "input": dict(step.get("input") or {}),
                "purpose": step.get("purpose") or f"调用 {step['tool']}",
            }
            for step in self.task_input.get("steps") or []
        ]

    def finalize(self, state: AgentState) -> dict[str, Any]:
        return {
            "summary": f"完成 {len(state.get('plan') or [])} 步",
            "artifacts": state.get("artifacts") or {},
            "citations": state.get("citations") or [],
        }