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

from app.services.report_service import KpNode, build_subjects, get_overview


def _nodes():
    return [
        KpNode(115, 7, None, "集合", 2, 0.8),
        KpNode(200, 7, 115, "集合运算", 3, 0.5),
        KpNode(201, 7, 200, "交集", 4, 0.3),
        KpNode(116, 7, None, "函数", 2, 1.0),
    ]


def test_build_subjects_radar_average_and_null():
    out = build_subjects(
        _nodes(),
        [(7, "高中数学")],
        mastery_raw={200: 0.6},
        mastery_t={200: 0.5},
    )
    assert len(out) == 1
    assert [m.kp_id for m in out[0].modules] == [115, 116]
    first = out[0].modules[0]
    assert (first.kp_count, first.assessed_count, first.mastery) == (3, 1, 0.5)
    assert out[0].modules[1].mastery is None
    assert out[0].modules[1].assessed_count == 0


def test_build_subjects_heatmap_parent_color_and_null():
    out = build_subjects(
        _nodes(),
        [(7, "高中数学")],
        mastery_raw={200: 0.6},
        mastery_t={200: 0.5},
    )
    by_id = {node.kp_id: node for node in out[0].heatmap}
    assert by_id[115].parent_id is None
    assert by_id[200].parent_id == 115
    assert by_id[201].parent_id == 200
    assert by_id[200].color_value == 0.5
    assert by_id[201].mastery is None
    assert by_id[201].color_value is None
    assert by_id[201].assessed is False


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeReportSession:
    """按 SQL 表名回放数据库行；不执行 WHERE。"""

    def __init__(
        self,
        *,
        nodes,
        subjects,
        mastery,
        notes=(),
        reviews=(),
        mistakes=(),
        mastered=(),
    ):
        self.nodes = nodes
        self.subjects = subjects
        self.mastery = mastery
        self.notes = notes
        self.reviews = reviews
        self.mistakes = mistakes
        self.mastered = mastered
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        sql = str(statement)
        if "knowledge_points" in sql:
            return _Rows(self.nodes)
        if "subjects" in sql:
            return _Rows(self.subjects)
        if "mastery" in sql:
            return _Rows(self.mastery)
        if "review_items" in sql:
            return _Rows(self.reviews)
        if "notes" in sql:
            return _Rows(self.notes)
        if "last_review_at" in sql:
            return _Rows(self.mastered)
        if "mistakes" in sql:
            return _Rows(self.mistakes)
        raise AssertionError(f"未分派的查询：{sql}")


def test_get_overview_builds_trend_and_filters_user():
    from decimal import Decimal

    session = FakeReportSession(
        nodes=[
            (115, 7, None, "集合", 2, Decimal("0.8")),
            (200, 7, 115, "集合运算", 3, Decimal("0.5")),
        ],
        subjects=[(7, "高中数学")],
        mastery=[(200, Decimal("0.6"), Decimal("2"), NOW)],
        notes=[(date(2026, 11, 12), 2)],
        reviews=[(date(2026, 11, 12), 1)],
        mistakes=[(date(2026, 11, 13), 3)],
        mastered=[(date(2026, 11, 13), 1)],
    )
    out = get_overview(session, user_id=50, range_key="7d", now=NOW)
    assert out.range.key == "7d"
    assert len(out.trend) == 7
    assert out.trend[-2].date == date(2026, 11, 13)
    assert out.trend[-2].new_mistakes == 3
    assert out.trend[-2].mastered_mistakes == 1
    assert out.subjects[0].modules[0].mastery == 0.6
    compiled = " || ".join(
        str(stmt.compile(compile_kwargs={"literal_binds": True}))
        for stmt in session.statements
    )
    assert "notes.user_id = 50" in compiled
    assert "review_items.user_id = 50" in compiled
    assert "mistakes.user_id = 50" in compiled
    assert "mastery.user_id = 50" in compiled


from app.services.report_service import (
    EMPTY_REPORT_MD,
    NumberValidation,
    allowed_numbers,
    build_weekly_stats,
    extract_numbers,
    validate_numbers,
)


def test_extract_numbers_ignores_markdown_list_markers():
    assert extract_numbers("1. 本周新增 3 条\n2) 复习 0 次") == ["3", "0"]


def test_extract_numbers_keeps_negative_and_decimal():
    assert extract_numbers("净增 -2，掌握度 0.351，日期 2026-11-14") == [
        "-2",
        "0.351",
        "2026",
        "11",
        "14",
    ]


def test_validate_numbers_allows_stats_and_date_parts():
    stats = {
        "period": {"from": "2026-11-08", "to": "2026-11-14", "days": 7},
        "totals": {"new_notes": 3, "mistakes_net": -2},
        "mastery": {"avg_mastery": 0.351},
    }
    result = validate_numbers("2026-11-14 新增 3 条，净增 -2，掌握度 0.351。", stats)
    assert result.ok is True
    assert result.invalid_numbers == []
    assert "3" in result.checked_numbers


def test_validate_numbers_rejects_invented_number():
    stats = {
        "period": {"from": "2026-11-08", "to": "2026-11-14", "days": 7},
        "totals": {"new_notes": 3},
    }
    result = validate_numbers("本周新增 999 条。", stats)
    assert result.ok is False
    assert result.invalid_numbers == ["999"]


def test_validate_numbers_rejects_report_without_numbers():
    result = validate_numbers("本周学习很认真。", {"totals": {"new_notes": 0}})
    assert result.ok is False


def test_allowed_numbers_includes_nested_values_and_dates():
    values = allowed_numbers(
        {"period": {"from": "2026-11-08", "days": 7}, "totals": {"new_notes": 3}}
    )
    assert {str(value) for value in values} >= {"2026", "11", "8", "7", "3"}


def test_build_weekly_stats_sums_and_weak_points():
    from decimal import Decimal

    session = FakeReportSession(
        nodes=[
            (115, 7, None, "集合", 2, Decimal("0.8")),
            (200, 7, 115, "集合运算", 3, Decimal("0.5")),
        ],
        subjects=[(7, "高中数学")],
        mastery=[(200, Decimal("0.6"), Decimal("2"), NOW)],
        notes=[(date(2026, 11, 12), 2)],
        reviews=[(date(2026, 11, 13), 1)],
        mistakes=[(date(2026, 11, 13), 3)],
        mastered=[],
    )
    out = build_weekly_stats(session, user_id=50, now=NOW)
    assert out.totals.new_notes == 2
    assert out.totals.reviews_done == 1
    assert out.totals.new_mistakes == 3
    assert out.totals.mistakes_net == 3
    assert out.active_days == 2
    assert out.mastery.assessed_kp_count == 1
    assert out.mastery.weak_modules[0].mastery == 0.6
    assert out.mastery.weak_kps[0].kp_id == 200
    assert len(out.trend) == 7
