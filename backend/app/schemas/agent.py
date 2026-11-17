"""S6-2 Agent 任务出入参（API.md §10）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentTaskCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: str = Field(min_length=1, max_length=50)
    input: dict[str, Any]


class AgentConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    comment: str | None = Field(default=None, max_length=500)
    edits: dict[str, Any] | None = None


class AgentStepOut(BaseModel):
    step_no: int
    thought: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: dict[str, Any] | None = None
    latency_ms: int | None = None
    status: str


class AgentTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_type: str
    status: str
    steps_count: int | None = None
    token_cost: int | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AgentTaskDetailOut(AgentTaskOut):
    input: dict[str, Any]
    result: dict[str, Any] | None = None
    steps: list[AgentStepOut] = Field(default_factory=list)