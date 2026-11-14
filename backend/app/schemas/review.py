"""S5-5 复习清单出入参（API.md §9）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ReviewItemOut(BaseModel):
    id: int
    kp_id: int
    kp_name: str
    subject_id: int
    ref_type: str
    ref_id: int
    ref_title: str | None = None
    ref_available: bool
    due_at: datetime
    interval_days: int = Field(ge=1, le=30)
    priority: float = Field(ge=0, le=1)
    estimated_minutes: int = Field(ge=1)
    mastery: float = Field(ge=0, le=1)
    mastery_t: float = Field(ge=0, le=1)
    stability: float = Field(gt=0)
    attempts: int = Field(ge=0)
    overdue_days: float = Field(ge=0)
    low_mastery: bool
    done_at: datetime | None = None


class ReviewTodayOut(BaseModel):
    date: str
    timezone: str
    items: list[ReviewItemOut]
    item_count: int = Field(ge=0)
    total_minutes: int = Field(ge=0)
    cap_minutes: int = Field(ge=1)
    truncated_count: int | None = Field(default=None, ge=0)