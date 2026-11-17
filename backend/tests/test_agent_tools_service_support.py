"""S6-1 工具所需的 service 增量：可编译 SQL + 掌握度批量折算。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.dialects import postgresql

from app.services import mastery_service, mistake_service, question_service


def _sql(stmt) -> str:  # noqa: ANN001
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_question_filters_new_fields_compile_into_sql():
    stmt = question_service.build_questions_query(
        filters=question_service.QuestionFilters(
            kp_ids=[101, 102],
            difficulty=3,
            exclude_user_id=50,
            exclude_done_since=datetime(2026, 11, 3, tzinfo=timezone.utc),
        )
    )
    sql = _sql(stmt)
    assert "question_kps.kp_id IN" in sql
    assert "questions.difficulty =" in sql
    assert "NOT (EXISTS" in sql
    assert "mistakes.user_id =" in sql


def test_question_filters_default_sql_unchanged():
    stmt = question_service.build_questions_query(filters=question_service.QuestionFilters())
    sql = _sql(stmt)
    assert "mistakes" not in sql
    assert "question_kps" not in sql


def test_mistake_filters_kp_ids_compiles_or_exists():
    stmt = mistake_service.build_mistakes_query(
        user_id=50, filters=mistake_service.MistakeFilters(kp_ids=[101, 102])
    )
    sql = _sql(stmt)
    assert "question_kps.kp_id IN" in sql
    assert "mistake_analyses.kp_ids" in sql


def test_mastery_details_marks_assessed_and_missing():
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)

    class _Rows:
        def __init__(self, rows):  # noqa: ANN001
            self._rows = rows

        def all(self):  # noqa: ANN201
            return self._rows

    class _Session:
        def __init__(self):  # noqa: ANN001
            self.calls = 0

        def execute(self, stmt):  # noqa: ANN001, ANN201
            self.calls += 1
            if self.calls == 1:
                return _Rows([(101, "函数", 7, None), (102, "定义域", 7, 0.8)])
            return _Rows([(101, 0.4, 2.0, now, 3, None)])

    states = mastery_service.mastery_details(
        _Session(), user_id=50, kp_ids=[101, 102, 999], now=now
    )
    assert [state.kp_id for state in states] == [101, 102]
    assert states[0].assessed is True
    assert states[0].mastery_t == 0.4
    assert states[0].attempts == 3
    assert states[1].assessed is False
    assert states[1].mastery_t is None
    assert states[1].exam_weight == 0.8


def test_mastery_details_empty_input_returns_empty():
    assert mastery_service.mastery_details(object(), user_id=50, kp_ids=[]) == []