"""S6-1 get_mastery：已评估/未评估/不存在三类区分。"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.ai.agents.tools import get_mastery as tool
from app.ai.agents.tools.base import ToolContext
from app.services.mastery_service import KpMasteryState

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def _state(kp_id: int, mastery_t: float | None, *, assessed: bool) -> KpMasteryState:
    return KpMasteryState(
        kp_id=kp_id,
        kp_name=f"知识点{kp_id}",
        subject_id=7,
        exam_weight=0.6,
        mastery_t=mastery_t,
        assessed=assessed,
        attempts=2 if assessed else 0,
        stability=2.0 if assessed else 1.0,
        last_practice_at=NOW if assessed else None,
        due_at=NOW if assessed else None,
    )


def _ctx() -> ToolContext:
    return ToolContext(session=object(), user=SimpleNamespace(id=50), now=NOW)  # type: ignore[arg-type]


def test_get_mastery_splits_assessed_unassessed_and_missing(monkeypatch):
    monkeypatch.setattr(
        tool.mastery_service,
        "mastery_details",
        lambda *a, **k: [_state(1, 0.32, assessed=True), _state(2, None, assessed=False)],
    )
    out = tool.get_mastery(_ctx(), tool.GetMasteryIn(kp_ids=[1, 2, 999]))
    assert [item.kp_id for item in out.items] == [1, 2]
    assert out.assessed_count == 1
    assert out.unassessed_kp_ids == [2]
    assert out.missing_kp_ids == [999]
    assert out.items[0].mastery_t == 0.32
    assert out.items[1].mastery_t is None
    assert out.items[1].assessed is False


def test_get_mastery_dedupes_ids(monkeypatch):
    captured = {}

    def fake(session, *, user_id, kp_ids, now):  # noqa: ANN001
        captured["kp_ids"] = kp_ids
        return []

    monkeypatch.setattr(tool.mastery_service, "mastery_details", fake)
    out = tool.get_mastery(_ctx(), tool.GetMasteryIn(kp_ids=[3, 3, 2]))
    assert captured["kp_ids"] == [3, 2]
    assert out.assessed_count == 0
    assert out.missing_kp_ids == [3, 2]