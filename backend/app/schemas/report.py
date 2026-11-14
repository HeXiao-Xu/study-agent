"""S5-6 学习报告出参（API.md §9）。"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReportRangeOut(BaseModel):
    """窗口回显；`from` 是 Python 关键字，字段名用 `from_` + alias 输出成 `from`。"""

    model_config = ConfigDict(populate_by_name=True)

    key: str
    from_: date = Field(alias="from")
    to: date


class ReportModuleOut(BaseModel):
    kp_id: int
    kp_name: str
    exam_weight: float | None = None
    kp_count: int
    assessed_count: int
    mastery: float | None = None


class ReportHeatmapNodeOut(BaseModel):
    kp_id: int
    kp_name: str
    parent_id: int | None = None
    level: int
    exam_weight: float | None = None
    mastery: float | None = None
    mastery_t: float | None = None
    color_value: float | None = None
    assessed: bool


class ReportSubjectOut(BaseModel):
    subject_id: int
    subject_name: str
    modules: list[ReportModuleOut]
    heatmap: list[ReportHeatmapNodeOut]


class ReportTrendPointOut(BaseModel):
    date: date
    new_notes: int
    reviews_done: int
    new_mistakes: int
    mastered_mistakes: int
    mistakes_net: int


class ReportOverviewOut(BaseModel):
    range: ReportRangeOut
    subjects: list[ReportSubjectOut]
    trend: list[ReportTrendPointOut]


class WeeklyPeriodOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: date = Field(alias="from")
    to: date
    days: int


class WeeklyTotalsOut(BaseModel):
    new_notes: int
    reviews_done: int
    new_mistakes: int
    mastered_mistakes: int
    mistakes_net: int


class WeeklyWeakModuleOut(BaseModel):
    subject_id: int
    kp_id: int
    kp_name: str
    mastery: float


class WeeklyWeakKpOut(BaseModel):
    subject_id: int
    kp_id: int
    kp_name: str
    level: int
    mastery: float


class WeeklyMasteryOut(BaseModel):
    assessed_kp_count: int
    avg_mastery: float | None = None
    weak_modules: list[WeeklyWeakModuleOut]
    weak_kps: list[WeeklyWeakKpOut]


class WeeklyStatsOut(BaseModel):
    totals: WeeklyTotalsOut
    active_days: int
    mastery: WeeklyMasteryOut
    trend: list[ReportTrendPointOut]


class NumberValidationOut(BaseModel):
    ok: bool
    attempts: int
    checked_numbers: list[str]
    invalid_numbers: list[str]


class WeeklyReportOut(BaseModel):
    period: WeeklyPeriodOut
    generated_by: Literal["llm", "empty"]
    report_md: str
    stats: WeeklyStatsOut
    validation: NumberValidationOut