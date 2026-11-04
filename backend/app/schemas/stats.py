"""S4-8 统计看板出参（API.md §4.7）。"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class StatsRangeOut(BaseModel):
    """窗口回显；`from` 是 Python 关键字，字段名用 `from_` + alias 输出成 `from`。"""

    # populate_by_name：内部用 from_= 构造，出参按 alias 序列化成 from
    model_config = ConfigDict(populate_by_name=True)

    key: str
    from_: date = Field(alias="from")
    to: date


class StatsSummaryOut(BaseModel):
    total: int
    pending: int
    corrected: int
    mastered: int
    analyzed: int
    with_kp: int
    mastery_rows: int


class StatsStatusCountOut(BaseModel):
    status: str
    count: int


class StatsCauseCountOut(BaseModel):
    cause_type: str
    count: int


class StatsTopKpOut(BaseModel):
    kp_id: int
    kp_name: str
    count: int
    mastery: float | None = None


class StatsTrendPointOut(BaseModel):
    date: date
    new_mistakes: int
    mastered: int


class StatsOverviewOut(BaseModel):
    range: StatsRangeOut
    summary: StatsSummaryOut
    by_status: list[StatsStatusCountOut]
    by_cause: list[StatsCauseCountOut]
    top_kps: list[StatsTopKpOut]
    trend: list[StatsTrendPointOut]