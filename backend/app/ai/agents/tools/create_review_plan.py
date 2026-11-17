"""S6-1 create_review_plan：未来 N 天的复习计划建议（不写 review_items）。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator

from app.ai.agents.tools.base import ToolContext, ToolInput, ToolOutput, ToolSpec
from app.core.config import get_settings
from app.services import mastery_service, review_service

PLANNED_DIFFICULTY = 3


class CreateReviewPlanIn(ToolInput):
    kp_ids: list[int] = Field(min_length=1, max_length=30)
    days: int = Field(default=3, ge=1, le=14)

    @field_validator("kp_ids")
    @classmethod
    def _dedupe(cls, value: list[int]) -> list[int]:
        return list(dict.fromkeys(value))


class ReviewPlanItem(ToolOutput):
    kp_id: int
    kp_name: str
    day: int
    date: date
    planned_minutes: int
    priority: float
    mastery_t: float | None = None
    reason: str


class ReviewPlanDay(ToolOutput):
    day: int
    date: date
    item_count: int
    total_minutes: int


class ReviewPlanOut(ToolOutput):
    days: int
    timezone: str
    total_minutes: int
    missing_kp_ids: list[int]
    items: list[ReviewPlanItem]
    by_day: list[ReviewPlanDay]


def _timezone() -> ZoneInfo:
    return ZoneInfo(get_settings().review_timezone)


def _day_dates(now: datetime, days: int) -> list[date]:
    """第一天 = 本地「明天」，避免与今日清单重复。"""
    tz = _timezone()
    _, _, local_date = review_service.local_bounds(now, tz)
    first = local_date + timedelta(days=1)
    return [first + timedelta(days=offset) for offset in range(days)]


def _priority(state: mastery_service.KpMasteryState, now: datetime) -> float:
    if state.assessed and state.mastery_t is not None:
        interval = review_service.review_interval_days(state.stability, state.mastery_t)
        overdue = (
            review_service.overdue_ratio(state.due_at, now, interval)
            if state.due_at is not None
            else 0.0
        )
        return review_service.review_priority(state.mastery_t, overdue, state.exam_weight)
    return review_service.review_priority(0.5, 0.0, state.exam_weight)


def create_review_plan(ctx: ToolContext, data: CreateReviewPlanIn) -> ReviewPlanOut:
    states = mastery_service.mastery_details(
        ctx.session,
        user_id=ctx.user.id,
        kp_ids=data.kp_ids,
        now=ctx.now,
    )
    found = {state.kp_id for state in states}
    ordered = sorted(
        states,
        key=lambda state: (
            0 if state.assessed and state.mastery_t is not None else 1,
            state.mastery_t if state.mastery_t is not None else 1.0,
            state.kp_id,
        ),
    )
    dates = _day_dates(ctx.now, data.days)
    minutes = review_service.estimated_minutes("question", PLANNED_DIFFICULTY)
    items: list[ReviewPlanItem] = []
    for index, state in enumerate(ordered):
        day_no = index % data.days
        if state.assessed and state.mastery_t is not None:
            reason = f"掌握度 {state.mastery_t:.2f}，建议优先复习"
        else:
            reason = "尚未评估，建议先做一次练习"
        items.append(
            ReviewPlanItem(
                kp_id=state.kp_id,
                kp_name=state.kp_name,
                day=day_no + 1,
                date=dates[day_no],
                planned_minutes=minutes,
                priority=_priority(state, ctx.now),
                mastery_t=state.mastery_t,
                reason=reason,
            )
        )
    by_day = [
        ReviewPlanDay(
            day=day_no + 1,
            date=dates[day_no],
            item_count=sum(1 for item in items if item.day == day_no + 1),
            total_minutes=sum(
                item.planned_minutes for item in items if item.day == day_no + 1
            ),
        )
        for day_no in range(data.days)
    ]
    return ReviewPlanOut(
        days=data.days,
        timezone=get_settings().review_timezone,
        total_minutes=sum(item.planned_minutes for item in items),
        missing_kp_ids=[kp_id for kp_id in data.kp_ids if kp_id not in found],
        items=items,
        by_day=by_day,
    )


SPEC = ToolSpec(
    name="create_review_plan",
    description=(
        "用途：给一批知识点排未来 N 天的复习计划建议；只返回计划，不写库。"
        "参数 kp_ids 为 1–30 个知识点，days 取 1–14。"
        "按掌握度从低到高轮转分配到各天（第一天为本地明天），每项 6 分钟，"
        "返回逐项优先级/日期/理由与每日汇总；未评估知识点排在最后并提示先做练习。"
    ),
    input_model=CreateReviewPlanIn,
    output_model=ReviewPlanOut,
    handler=create_review_plan,
)