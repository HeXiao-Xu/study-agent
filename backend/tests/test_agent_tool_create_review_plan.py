"""S6-1 create_review_plan：只出建议、不写库。"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.ai.agents.tools import create_review_plan as tool
from app.ai.agents.tools.base import ToolContext
from app.services.mastery_service import KpMasteryState

NOW = datetime(2026, 11, 17, 6, 0, tzinfo=timezone.utc)


def _state(
    kp_id: int,
    mastery_t: float | None,
    *,
    assessed: bool = True,
    exam_weight: float | None = None,
    due_at: datetime | None = None,
) -> KpMasteryState:
    return KpMasteryState(
        kp_id=kp_id,
        kp_name=f"知识点{kp_id}",
        subject_id=7,
        exam_weight=exam_weight,
        mastery_t=mastery_t,
        assessed=assessed,
        attempts=1 if assessed else 0,
        stability=2.0,
        last_practice_at=NOW if assessed else None,
        due_at=due_at,
    )


def _ctx() -> ToolContext:
    return ToolContext(session=object(), user=SimpleNamespace(id=50), now=NOW)  # type: ignore[arg-type]


def test_review_plan_orders_weak_first_and_rotates_days(monkeypatch):
    monkeypatch.setattr(
        tool.mastery_service,
        "mastery_details",
        lambda *a, **k: [
            _state(1, 0.8),
            _state(2, 0.2),
            _state(3, None, assessed=False),
        ],
    )
    out = tool.create_review_plan(
        _ctx(), tool.CreateReviewPlanIn(kp_ids=[1, 2, 3], days=2)
    )
    assert [item.kp_id for item in out.items] == [2, 1, 3]
    assert [item.day for item in out.items] == [1, 2, 1]
    assert out.items[2].mastery_t is None
    assert "尚未评估" in out.items[2].reason
    assert out.total_minutes == 18
    assert [day.day for day in out.by_day] == [1, 2]
    assert out.by_day[0].item_count == 2


def test_review_plan_first_day_is_tomorrow_local():
    dates = tool._day_dates(NOW, 3)
    assert [day.isoformat() for day in dates] == ["2026-11-18", "2026-11-19", "2026-11-20"]


def test_review_plan_reports_missing_ids(monkeypatch):
    monkeypatch.setattr(
        tool.mastery_service,
        "mastery_details",
        lambda *a, **k: [_state(1, 0.5)],
    )
    out = tool.create_review_plan(
        _ctx(), tool.CreateReviewPlanIn(kp_ids=[1, 999], days=1)
    )
    assert out.missing_kp_ids == [999]
    assert [item.kp_id for item in out.items] == [1]