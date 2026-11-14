"""S5-5 复习调度（spec §4）。

前半部分是纯函数，便于手推与单测；DB 用例在后续任务补。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.models.enums import ReviewRefType

LOW_MASTERY = 0.4
DEFAULT_CAP_MINUTES = 35
ESTIMATE_BASE_MINUTES: dict[str, int] = {
    ReviewRefType.NOTE.value: 3,
    ReviewRefType.QUESTION.value: 3,
    ReviewRefType.MISTAKE.value: 4,
}
ACTION_DONE = "done"
ACTION_SKIP = "skip"
ACTION_LATER = "later"


@dataclass(frozen=True, slots=True)
class MasterySnapshot:
    kp_id: int
    kp_name: str
    subject_id: int
    exam_weight: float | None
    mastery: float
    stability: float
    attempts: int
    last_practice_at: datetime | None
    due_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RefChoice:
    ref_type: str
    ref_id: int
    difficulty: int


@dataclass(frozen=True, slots=True)
class ItemPlan:
    kp_id: int
    kp_name: str
    subject_id: int
    ref_type: str
    ref_id: int
    due_at: datetime
    interval_days: int
    priority: float
    estimated_minutes: int
    mastery: float
    mastery_t: float
    stability: float
    attempts: int
    overdue_days: float
    low_mastery: bool


@dataclass(frozen=True, slots=True)
class RefDetail:
    title: str | None
    available: bool
    difficulty: int


@dataclass(frozen=True, slots=True)
class ReviewRowSnapshot:
    item: object
    kp_name: str
    subject_id: int
    exam_weight: float | None
    mastery: float
    stability: float
    attempts: int
    last_practice_at: datetime | None


def _timezone() -> ZoneInfo:
    return ZoneInfo(get_settings().review_timezone)


def local_bounds(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime, date]:
    local = now.astimezone(tz)
    start = datetime.combine(local.date(), time.min, tzinfo=tz)
    next_start = start + timedelta(days=1)
    return start.astimezone(timezone.utc), next_start.astimezone(timezone.utc), local.date()


def overdue_days(due_at: datetime, now: datetime) -> float:
    return round(max(0.0, (now - due_at).total_seconds() / 86400.0), 2)


def overdue_ratio(due_at: datetime, now: datetime, interval_days: int) -> float:
    days = max(0.0, (now - due_at).total_seconds() / 86400.0)
    return round(min(1.0, days / max(1, interval_days)), 4)


def review_priority(mastery_t: float, overdue: float, exam_weight: float | None) -> float:
    weight = 0.5 if exam_weight is None else float(exam_weight)
    raw = 0.5 * (1.0 - mastery_t) + 0.3 * overdue + 0.2 * weight
    return round(min(1.0, max(0.0, raw)), 4)


def estimated_minutes(ref_type: str, difficulty: int) -> int:
    safe_difficulty = min(5, max(1, int(difficulty)))
    return ESTIMATE_BASE_MINUTES.get(ref_type, 3) + safe_difficulty


def is_candidate(mastery_t: float, due_at: datetime, *, next_start: datetime) -> bool:
    return mastery_t < LOW_MASTERY or due_at < next_start


def _sort_key(plan: ItemPlan) -> tuple[float, float, int]:
    return (-plan.priority, plan.mastery_t, plan.kp_id)


def select_capped(
    plans: Sequence[ItemPlan], cap_minutes: int
) -> tuple[list[ItemPlan], list[ItemPlan]]:
    selected: list[ItemPlan] = []
    deferred: list[ItemPlan] = []
    total = 0
    for plan in sorted(plans, key=_sort_key):
        if not selected or total + plan.estimated_minutes <= cap_minutes:
            selected.append(plan)
            total += plan.estimated_minutes
        else:
            deferred.append(plan)
    return selected, deferred