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

from types import SimpleNamespace

from app.core.exceptions import ConflictError, NotFoundError
from app.schemas.review import ReviewItemOut, ReviewTodayOut
from app.services.review_service import (
    MasterySnapshot,
    RefChoice,
    ReviewRowSnapshot,
)


class FakeSession:
    def __init__(self, *, scalar=None):
        self.scalar_value = scalar
        self.flushed = 0

    def scalar(self, stmt):
        return self.scalar_value

    def flush(self):
        self.flushed += 1


def _snapshot(
    kp_id: int = 117,
    *,
    mastery=0.2,
    stability=2.0,
    last_practice=None,
    weight=0.8,
):
    return MasterySnapshot(
        kp_id=kp_id,
        kp_name=f"知识点{kp_id}",
        subject_id=7,
        exam_weight=weight,
        mastery=mastery,
        stability=stability,
        attempts=2,
        last_practice_at=last_practice,
        due_at=datetime(2026, 11, 13, tzinfo=timezone.utc),
    )


def _today() -> ReviewTodayOut:
    return ReviewTodayOut(
        date="2026-11-14",
        timezone="Asia/Shanghai",
        items=[],
        item_count=0,
        total_minutes=0,
        cap_minutes=35,
        truncated_count=None,
    )


def test_refresh_user_creates_plan_and_does_not_commit(monkeypatch):
    now = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
    refs = {117: RefChoice(ref_type="question", ref_id=501, difficulty=3)}
    upserts = []
    session = FakeSession()

    monkeypatch.setattr(review_service, "_load_mastery_snapshots", lambda s, *a, **k: [_snapshot()])
    monkeypatch.setattr(review_service, "_load_ref_choices", lambda s, *a, **k: refs)
    monkeypatch.setattr(review_service, "_load_items", lambda s, *a, **k: {})
    monkeypatch.setattr(review_service, "_upsert_item", lambda s, **kw: upserts.append(kw))
    monkeypatch.setattr(review_service, "get_today", lambda s, *a, **k: _today())

    result = review_service.refresh_user(session, user_id=50, now=now)

    assert result.item_count == 0
    assert len(upserts) == 1
    assert upserts[0]["plan"].kp_id == 117
    assert upserts[0]["clear_done"] is False
    assert session.flushed == 1


def test_refresh_user_skips_item_done_today(monkeypatch):
    now = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
    done_today = SimpleNamespace(done_at=datetime(2026, 11, 14, 0, 30, tzinfo=timezone.utc))
    session = FakeSession()
    monkeypatch.setattr(review_service, "_load_mastery_snapshots", lambda s, *a, **k: [_snapshot()])
    monkeypatch.setattr(
        review_service,
        "_load_ref_choices",
        lambda s, *a, **k: {117: RefChoice("question", 501, 3)},
    )
    monkeypatch.setattr(review_service, "_load_items", lambda s, *a, **k: {117: done_today})
    monkeypatch.setattr(review_service, "_upsert_item", lambda s, **kw: None)
    monkeypatch.setattr(review_service, "get_today", lambda s, *a, **k: _today())

    review_service.refresh_user(session, user_id=50, now=now)

    assert not hasattr(session, "upserts") or session.upserts == []


def test_refresh_user_reactivates_done_yesterday(monkeypatch):
    now = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
    old = SimpleNamespace(done_at=datetime(2026, 11, 12, 1, 0, tzinfo=timezone.utc))
    upserts = []
    session = FakeSession()
    monkeypatch.setattr(review_service, "_load_mastery_snapshots", lambda s, *a, **k: [_snapshot()])
    monkeypatch.setattr(
        review_service,
        "_load_ref_choices",
        lambda s, *a, **k: {117: RefChoice("question", 501, 3)},
    )
    monkeypatch.setattr(review_service, "_load_items", lambda s, *a, **k: {117: old})
    monkeypatch.setattr(review_service, "_upsert_item", lambda s, **kw: upserts.append(kw))
    monkeypatch.setattr(review_service, "get_today", lambda s, *a, **k: _today())

    review_service.refresh_user(session, user_id=50, now=now)

    assert upserts[0]["clear_done"] is True


def test_refresh_user_skips_candidate_without_ref(monkeypatch):
    now = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
    session = FakeSession()
    monkeypatch.setattr(review_service, "_load_mastery_snapshots", lambda s, *a, **k: [_snapshot()])
    monkeypatch.setattr(review_service, "_load_ref_choices", lambda s, *a, **k: {})
    monkeypatch.setattr(review_service, "_load_items", lambda s, *a, **k: {})
    monkeypatch.setattr(review_service, "_upsert_item", lambda s, **kw: None)
    monkeypatch.setattr(review_service, "get_today", lambda s, *a, **k: _today())

    review_service.refresh_user(session, user_id=50, now=now)

    assert session.flushed == 1


def test_get_today_returns_empty_without_mastery(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(review_service, "_load_today_snapshots", lambda s, *a, **k: [])
    result = review_service.get_today(
        session, user_id=50, now=datetime(2026, 11, 14, tzinfo=timezone.utc)
    )
    assert result.items == []
    assert result.item_count == 0


def test_get_today_builds_item_with_ref_detail(monkeypatch):
    now = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
    item = SimpleNamespace(
        id=9,
        kp_id=117,
        ref_type="question",
        ref_id=501,
        interval_days=2,
        due_at=now,
        done_at=None,
    )
    snapshot = ReviewRowSnapshot(
        item=item,
        kp_name="函数",
        subject_id=7,
        exam_weight=1.0,
        mastery=0.5,
        stability=2.0,
        attempts=2,
        last_practice_at=None,
    )
    monkeypatch.setattr(review_service, "_load_today_snapshots", lambda s, *a, **k: [snapshot])
    monkeypatch.setattr(
        review_service,
        "_ref_details",
        lambda s, *a, **k: {("question", 501): review_service.RefDetail("题干", True, 3)},
    )

    result = review_service.get_today(FakeSession(), user_id=50, now=now)

    assert result.item_count == 1
    assert result.items[0].ref_title == "题干"
    assert result.items[0].priority > 0


def test_mark_item_done_writes_done_at(monkeypatch):
    now = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
    item = SimpleNamespace(
        id=9,
        user_id=50,
        kp_id=117,
        ref_type="question",
        ref_id=501,
        interval_days=2,
        done_at=None,
        due_at=now,
    )
    session = FakeSession(scalar=item)
    snapshot = ReviewRowSnapshot(
        item=item,
        kp_name="函数",
        subject_id=7,
        exam_weight=1.0,
        mastery=0.2,
        stability=2.0,
        attempts=2,
        last_practice_at=None,
    )
    monkeypatch.setattr(review_service, "_load_item_snapshot", lambda s, *a, **k: snapshot)
    monkeypatch.setattr(
        review_service,
        "_ref_details",
        lambda s, *a, **k: {("question", 501): review_service.RefDetail("题干", True, 3)},
    )

    result = review_service.mark_item(session, user_id=50, item_id=9, action="done", now=now)

    assert item.done_at == now
    assert isinstance(result, ReviewItemOut)
    assert session.flushed == 1


def test_mark_item_rejects_completed_and_missing(monkeypatch):
    now = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
    completed = SimpleNamespace(id=9, user_id=50, done_at=now, due_at=now)
    monkeypatch.setattr(review_service, "_load_item_snapshot", lambda s, *a, **k: None)
    with pytest.raises(ConflictError, match="已完成"):
        review_service.mark_item(
            FakeSession(scalar=completed), user_id=50, item_id=9, action="done", now=now
        )
    with pytest.raises(NotFoundError, match="不存在"):
        review_service.mark_item(
            FakeSession(scalar=None), user_id=50, item_id=99, action="done", now=now
        )
