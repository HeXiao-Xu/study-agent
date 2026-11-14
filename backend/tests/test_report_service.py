"""S5-6 报告 service：窗口、趋势补零、模块/热力、周报统计、数字校验。"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.core.exceptions import InvalidParamError
from app.services import report_service

NOW = datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc)


def test_build_window_30d_has_thirty_utc_days():
    window = report_service.build_window("30d", now=NOW)
    assert window.key == "30d"
    assert window.days == 30
    assert len(window.dates) == 30
    assert window.dates[0] == date(2026, 10, 16)
    assert window.dates[-1] == date(2026, 11, 14)
    assert window.start == datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc)
    assert window.end == NOW


def test_build_window_rejects_unknown_range():
    with pytest.raises(InvalidParamError) as exc:
        report_service.build_window("365d", now=NOW)
    assert "365d" in str(exc.value)


def test_build_trend_fills_zero_and_computes_net():
    dates = [date(2026, 11, 12), date(2026, 11, 13), date(2026, 11, 14)]
    points = report_service.build_trend(
        dates,
        new_notes={date(2026, 11, 12): 2},
        reviews_done={date(2026, 11, 13): 1},
        new_mistakes={date(2026, 11, 13): 3},
        mastered_mistakes={date(2026, 11, 13): 1},
    )
    assert [
        (
            p.date,
            p.new_notes,
            p.reviews_done,
            p.new_mistakes,
            p.mastered_mistakes,
            p.mistakes_net,
        )
        for p in points
    ] == [
        (date(2026, 11, 12), 2, 0, 0, 0, 0),
        (date(2026, 11, 13), 0, 1, 3, 1, 2),
        (date(2026, 11, 14), 0, 0, 0, 0, 0),
    ]