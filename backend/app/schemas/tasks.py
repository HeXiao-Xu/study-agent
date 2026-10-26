"""S2-7 异步任务出入参。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DemoTaskIn(BaseModel):
    seconds: int = Field(default=5, ge=1, le=10)
    fail: bool = False


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str
    created_at: datetime


class TaskDetailOut(TaskOut):
    attempts: int
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None