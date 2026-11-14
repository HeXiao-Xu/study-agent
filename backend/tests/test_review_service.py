"""S5-5 复习调度纯函数：边界、优先级、时长、装填。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services import review_service
from app.services.review_service import ItemPlan

TZ = ZoneInfo("Asia/Shanghai")


def _plan(kp_id: int, *, priority: float, mastery_t: float, minutes: int) -> ItemPlan:
    return ItemPlan(
        kp_id=kp_id,
        kp_name=f"知识点{kp_id}",
        subject_id=7,
        ref_type="question",
        ref_id=kp_id * 10,
        due_at=datetime(2026, 11, 14, tzinfo=timezone.utc),
        interval_days=2,
        priority=priority,
        estimated_minutes=minutes,
        mastery=mastery_t,
        mastery_t=mastery_t,
        stability=2.0,
        attempts=1,
        overdue_days=0.0,
        low_mastery=mastery_t < 0.4,
    )


def test_local_bounds_uses_local_midnight():
    now = datetime(2026, 11, 14, 0, 30, tzinfo=timezone.utc)  # 北京 08:30
    start, next_start, local_date = review_service.local_bounds(now, TZ)
    assert local_date == date(2026, 11, 14)
    assert start == datetime(2026, 11, 13, 16, 0, tzinfo=timezone.utc)
    assert next_start == datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc)


def test_overdue_days_and_ratio():
    now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    due = now - timedelta(days=2)
    assert review_service.overdue_days(due, now) == pytest.approx(2.0)
    assert review_service.overdue_ratio(due, now, 4) == pytest.approx(0.5)
    assert review_service.overdue_ratio(now + timedelta(days=1), now, 4) == 0.0
    assert review_service.overdue_ratio(due, now, 1) == 1.0


def test_review_priority_formula_and_weight_fallback():
    assert review_service.review_priority(0.0, 1.0, 1.0) == 1.0
    assert review_service.review_priority(1.0, 0.0, 0.5) == 0.1
    assert review_service.review_priority(0.5, 0.0, None) == pytest.approx(0.35)
    assert review_service.review_priority(0.2, 0.7, 1.0) == pytest.approx(0.81)


def test_estimated_minutes_scales_with_difficulty():
    assert review_service.estimated_minutes("question", 3) == 6
    assert review_service.estimated_minutes("mistake", 3) == 7
    assert review_service.estimated_minutes("note", 3) == 6
    assert review_service.estimated_minutes("question", 99) == 8


def test_is_candidate_low_mastery_even_before_due():
    next_start = datetime(2026, 11, 15, tzinfo=timezone.utc)
    due_future = datetime(2026, 11, 20, tzinfo=timezone.utc)
    assert review_service.is_candidate(0.39, due_future, next_start=next_start) is True
    assert review_service.is_candidate(0.4, due_future, next_start=next_start) is False
    due_today = next_start - timedelta(seconds=1)
    assert review_service.is_candidate(0.9, due_today, next_start=next_start) is True
    assert review_service.is_candidate(0.9, next_start, next_start=next_start) is False


def test_select_capped_takes_priority_order_and_defers_rest():
    plans = [
        _plan(1, priority=0.2, mastery_t=0.8, minutes=6),
        _plan(2, priority=0.9, mastery_t=0.2, minutes=6),
        _plan(3, priority=0.5, mastery_t=0.5, minutes=6),
    ]
    selected, deferred = review_service.select_capped(plans, 12)
    assert [item.kp_id for item in selected] == [2, 3]
    assert [item.kp_id for item in deferred] == [1]
    assert sum(item.estimated_minutes for item in selected) == 12


def test_select_capped_keeps_one_even_if_over_cap():
    plans = [_plan(1, priority=0.9, mastery_t=0.2, minutes=9)]
    selected, deferred = review_service.select_capped(plans, 5)
    assert [item.kp_id for item in selected] == [1]
    assert deferred == []


def test_select_capped_tie_breaks_by_mastery_then_kp_id():
    plans = [
        _plan(2, priority=0.5, mastery_t=0.5, minutes=5),
        _plan(1, priority=0.5, mastery_t=0.5, minutes=5),
    ]
    selected, _ = review_service.select_capped(plans, 35)
    assert [item.kp_id for item in selected] == [1, 2]