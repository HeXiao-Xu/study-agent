"""S4-8 统计看板：窗口、补零、四维聚合、权限过滤（FakeSession 只验 SQL 口径）。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.exceptions import InvalidParamError
from app.services import stats_service

NOW = datetime(2026, 11, 4, 13, 0, tzinfo=timezone.utc)


class _Rows:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows


class FakeStatsSession:
    """按 SQL 里的表名/函数名分派：假会话不执行 WHERE，只回放"数据库会给的行"。"""

    def __init__(
        self,
        *,
        status_rows: list[tuple] | None = None,
        cause_rows: list[tuple] | None = None,
        kp_rows: list[tuple] | None = None,
        new_rows: list[tuple] | None = None,
        mastered_rows: list[tuple] | None = None,
        mastery_rows: list[tuple] | None = None,
        analyzed: int = 0,
        with_kp: int = 0,
        mastery_count: int = 0,
    ) -> None:
        self.status_rows = status_rows or []
        self.cause_rows = cause_rows or []
        self.kp_rows = kp_rows or []
        self.new_rows = new_rows or []
        self.mastered_rows = mastered_rows or []
        self.mastery_rows = mastery_rows or []
        self.analyzed = analyzed
        self.with_kp = with_kp
        self.mastery_count = mastery_count
        self.statements: list[object] = []

    def execute(self, statement):  # noqa: ANN001, ANN201
        self.statements.append(statement)
        sql = str(statement)
        if "mistake_analyses" in sql and "cause_type" in sql:
            return _Rows(self.cause_rows)
        if "knowledge_points" in sql:
            return _Rows(self.kp_rows)
        if "mastery" in sql:
            return _Rows(self.mastery_rows)
        if "date_trunc" in sql and "last_review_at" in sql:
            return _Rows(self.mastered_rows)
        if "date_trunc" in sql:
            return _Rows(self.new_rows)
        return _Rows(self.status_rows)

    def scalar(self, statement):  # noqa: ANN001, ANN201
        self.statements.append(statement)
        sql = str(statement)
        if "mistake_analyses" in sql:
            return self.analyzed
        if "question_kps" in sql:
            return self.with_kp
        if "mastery" in sql:
            return self.mastery_count
        raise AssertionError(f"未分派的 scalar: {sql}")


def test_build_window_30d_has_thirty_days() -> None:
    window = stats_service.build_window("30d", now=NOW)
    assert window.key == "30d"
    assert window.days == 30
    assert len(window.dates) == 30
    assert window.dates[-1] == date(2026, 11, 4)
    assert window.dates[0] == date(2026, 10, 6)
    assert window.start == datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc)
    assert window.end == NOW


def test_build_window_7d_and_90d_lengths() -> None:
    assert len(stats_service.build_window("7d", now=NOW).dates) == 7
    assert len(stats_service.build_window("90d", now=NOW).dates) == 90


def test_build_window_rejects_unknown_range() -> None:
    with pytest.raises(InvalidParamError) as exc:
        stats_service.build_window("365d", now=NOW)
    assert "365d" in str(exc.value)


def test_fill_days_pads_missing_days() -> None:
    dates = [date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3)]
    assert stats_service.fill_days({date(2026, 11, 2): 5}, dates) == [
        (date(2026, 11, 1), 0),
        (date(2026, 11, 2), 5),
        (date(2026, 11, 3), 0),
    ]


def test_overview_builds_all_four_blocks() -> None:
    session = FakeStatsSession(
        status_rows=[("待订正", 33), ("已订正", 1)],
        cause_rows=[("概念不清", 11), ("计算失误", 6)],
        kp_rows=[(197, "同角三角函数基本关系", 1)],
        new_rows=[(date(2026, 11, 3), 34)],
        mastered_rows=[],
        mastery_rows=[(197, "0.144", "1.00", NOW)],
        analyzed=34,
        with_kp=3,
        mastery_count=5,
    )
    out = stats_service.overview(session, user_id=50, range_key="30d", now=NOW)
    assert out.range.key == "30d"
    assert out.range.from_ == date(2026, 10, 6)
    assert out.range.to == date(2026, 11, 4)
    assert out.summary.total == 34
    assert out.summary.pending == 33
    assert out.summary.corrected == 1
    assert out.summary.mastered == 0
    assert out.summary.analyzed == 34
    assert out.summary.with_kp == 3
    assert out.summary.mastery_rows == 5
    assert out.by_cause[0].cause_type == "概念不清"
    assert out.top_kps[0].kp_id == 197
    assert out.top_kps[0].mastery == pytest.approx(0.144)
    assert len(out.trend) == 30
    assert out.trend[-1].date == date(2026, 11, 4)


def test_overview_status_rows_always_three() -> None:
    session = FakeStatsSession(status_rows=[("待订正", 2)])
    out = stats_service.overview(session, user_id=50, range_key="7d", now=NOW)
    assert [(row.status, row.count) for row in out.by_status] == [
        ("待订正", 2),
        ("已订正", 0),
        ("已掌握", 0),
    ]


def test_overview_trend_pads_zero_and_accumulates_mastered() -> None:
    session = FakeStatsSession(
        new_rows=[(date(2026, 11, 3), 34)],
        mastered_rows=[(date(2026, 10, 1), 2), (date(2026, 11, 3), 1)],
    )
    out = stats_service.overview(session, user_id=50, range_key="7d", now=NOW)
    trend = [(point.date, point.new_mistakes, point.mastered) for point in out.trend]
    assert trend[0] == (date(2026, 10, 29), 0, 2)  # 窗口前的 2 条算进起点
    assert trend[-2] == (date(2026, 11, 3), 34, 3)
    assert trend[-1] == (date(2026, 11, 4), 0, 3)


def test_overview_top_kp_mastery_none_when_no_row() -> None:
    session = FakeStatsSession(kp_rows=[(120, "数列", 1)], mastery_rows=[])
    out = stats_service.overview(session, user_id=50, range_key="30d", now=NOW)
    assert out.top_kps[0].mastery is None


def test_overview_every_statement_filters_user() -> None:
    session = FakeStatsSession(
        status_rows=[("待订正", 1)], kp_rows=[(120, "数列", 1)]
    )
    stats_service.overview(session, user_id=50, range_key="30d", now=NOW)
    compiled = " || ".join(
        str(stmt.compile(compile_kwargs={"literal_binds": True}))
        for stmt in session.statements
    )
    assert "mistakes.user_id = 50" in compiled
    # date_trunc 的单位必须是字面量，否则 PG 无法把 SELECT 与 GROUP BY 认成同一表达式
    assert "date_trunc('day', mistakes.created_at)" in compiled
    assert "date_trunc('day', mistakes.last_review_at)" in compiled
    assert "mastery.user_id = 50" in compiled
    assert "mistakes.created_at >=" in compiled


def test_mastery_values_returns_decayed_map() -> None:
    from app.services import mastery_service

    session = FakeStatsSession(
        mastery_rows=[(197, "0.800", "10.00", NOW - timedelta(days=10))]
    )
    values = mastery_service.mastery_values(session, user_id=50, kp_ids=[197], now=NOW)
    assert values[197] == pytest.approx(0.294)