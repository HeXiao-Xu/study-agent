"""S3-7 用量统计响应模型（API.md §11）。"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class UsageTotals(BaseModel):
    calls: int = 0
    failed_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_yuan: float = 0.0
    avg_latency_ms: float = 0.0


class UsageItem(BaseModel):
    date: date
    scene: str
    model: str
    calls: int = 0
    failed_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_yuan: float = 0.0
    avg_latency_ms: float = 0.0


class UsageReport(BaseModel):
    range: Literal["1d", "7d", "30d"]
    start_date: date
    end_date: date
    totals: UsageTotals = Field(default_factory=UsageTotals)
    items: list[UsageItem] = Field(default_factory=list)