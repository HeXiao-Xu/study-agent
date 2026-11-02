"""S4-2 错题服务：录入幂等、状态机、权限隔离、筛选 SQL、统计。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import InvalidParamError, NotFoundError
from app.models.enums import MistakeStatus
from app.models.mistake import Mistake
from app.models.question import Question
from app.schemas.mistake import MistakeCreateIn, MistakeUpdateIn
from app.services import mistake_service
from app.utils.pagination import PageParams, SortParams


class _Rows:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows


class FakeSession:
    def __init__(self, *, objects=None, scalar_results=None, scalars_results=None, rows_results=None) -> None:
        self.objects = objects or {}
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.rows_results = list(rows_results or [])
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.scalar_statements: list[object] = []
        self.execute_statements: list[object] = []
        self._next_id = 500

    def get(self, entity, pk):
        return self.objects.get((entity, pk))

    def scalar(self, statement):
        self.scalar_statements.append(statement)
        return self.scalar_results.pop(0) if self.scalar_results else None

    def scalars(self, statement):
        return self.scalars_results.pop(0) if self.scalars_results else []

    def execute(self, statement):
        self.execute_statements.append(statement)
        return _Rows(self.rows_results.pop(0) if self.rows_results else [])

    def add(self, instance) -> None:
        if getattr(instance, "id", None) is None:
            self._next_id += 1
            instance.id = self._next_id
        # 模拟 DB 的 server_default=now()：真实 PG 在 commit 后才有值，
        # FakeSession 没有 flush/refresh，不补这一行 MistakeDetailOut.created_at 会拿到 None。
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime(2026, 11, 3, tzinfo=timezone.utc)
        self.added.append(instance)

    def flush(self) -> None:
        return None

    def delete(self, instance) -> None:
        self.deleted.append(instance)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _question(question_id: int = 65, *, answer: str | None = "B") -> Question:
    question = Question(
        subject_id=7, stem_md="已知函数 $f(x)=x^2-4x+3$", stem_hash="h1", qtype="解答",
        difficulty=2, origin="upload", answer_md=answer, verified=True,
    )
    question.id = question_id
    return question


def _mistake(
    mistake_id: int = 12,
    *,
    user_id: int = 1,
    status: str = "待订正",
    streak: int = 0,
    last_review_at: datetime | None = None,
) -> Mistake:
    mistake = Mistake(
        user_id=user_id, question_id=65, status=status, correct_streak=streak,
        created_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
        last_review_at=last_review_at,
    )
    mistake.id = mistake_id
    return mistake


def test_create_from_question_new_row_uses_question_answer():
    question = _question()
    session = FakeSession(objects={(Question, 65): question}, scalar_results=[None])
    detail, created = mistake_service.create_from_question(
        session, user_id=1, payload=MistakeCreateIn(question_id=65)
    )
    assert created is True
    assert session.commits == 1
    saved = session.added[0]
    assert isinstance(saved, Mistake)
    assert saved.correct_answer_md == "B"
    assert saved.status == MistakeStatus.TODO.value
    assert detail.question_id == 65


def test_create_from_question_reuses_existing_and_resets():
    reviewed_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    existing = _mistake(status="已掌握", streak=2, last_review_at=reviewed_at)
    session = FakeSession(
        objects={(Question, 65): _question(), (Mistake, 12): existing}, scalar_results=[existing]
    )
    detail, created = mistake_service.create_from_question(
        session, user_id=1, payload=MistakeCreateIn(question_id=65, my_answer_md="我又错了")
    )
    assert created is False
    assert existing.status == MistakeStatus.TODO.value
    assert existing.correct_streak == 0
    # d-1：录入不是复习，复用重置既不清零也不覆盖「复习时间」。
    assert existing.last_review_at == reviewed_at
    assert detail.last_review_at == reviewed_at
    assert existing.my_answer_md == "我又错了"
    assert session.commits == 1


def test_create_from_question_concurrent_insert_reuses_winner(monkeypatch):
    reviewed_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    winner = _mistake(status="已掌握", streak=2, last_review_at=reviewed_at)
    session = FakeSession(
        objects={(Question, 65): _question()},
        scalar_results=[None, winner],  # 首次复查询为空 → 并发赢家
    )
    real_commit = session.commit
    attempts = {"n": 0}

    def flaky_commit() -> None:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise IntegrityError("INSERT INTO mistakes", {}, Exception("duplicate key"))
        real_commit()

    monkeypatch.setattr(session, "commit", flaky_commit)
    detail, created = mistake_service.create_from_question(
        session, user_id=1, payload=MistakeCreateIn(question_id=65, my_answer_md="并发作答")
    )
    assert created is False
    assert session.commits == 1
    assert session.rollbacks == 1
    assert winner.status == MistakeStatus.TODO.value
    assert winner.correct_streak == 0
    assert winner.last_review_at == reviewed_at
    assert winner.my_answer_md == "并发作答"
    assert detail.id == winner.id


def test_create_from_question_missing_question_raises_404():
    session = FakeSession(objects={})
    with pytest.raises(NotFoundError):
        mistake_service.create_from_question(session, user_id=1, payload=MistakeCreateIn(question_id=404))


def test_get_detail_other_user_raises_404():
    session = FakeSession(objects={(Mistake, 12): _mistake(user_id=2)})
    with pytest.raises(NotFoundError):
        mistake_service.get_detail(session, user_id=1, mistake_id=12)


def test_update_mistake_rejects_null_status():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MistakeUpdateIn(status=None)


def test_update_mistake_rejects_unknown_status():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MistakeUpdateIn(status="已通关")


def test_update_mistake_changes_answer_only():
    mistake = _mistake()
    session = FakeSession(
        objects={(Mistake, 12): mistake, (Question, 65): _question()},
        scalars_results=[[], []],  # kp 名 + cause 各一次（_detail 内部）
    )
    mistake_service.update_mistake(
        session, user_id=1, mistake_id=12, payload=MistakeUpdateIn(my_answer_md="x=2")
    )
    assert mistake.my_answer_md == "x=2"
    assert mistake.status == MistakeStatus.TODO.value
    assert session.commits == 1


def test_update_mistake_clears_answer_with_explicit_null():
    mistake = _mistake()
    mistake.my_answer_md = "旧作答"
    session = FakeSession(
        objects={(Mistake, 12): mistake, (Question, 65): _question()},
        scalars_results=[[], []],
    )
    mistake_service.update_mistake(
        session, user_id=1, mistake_id=12, payload=MistakeUpdateIn(my_answer_md=None)
    )
    assert mistake.my_answer_md is None
    assert session.commits == 1


def test_update_mistake_keeps_answer_when_field_omitted():
    mistake = _mistake()
    mistake.my_answer_md = "旧作答"
    session = FakeSession(
        objects={(Mistake, 12): mistake, (Question, 65): _question()},
        scalars_results=[[], []],
    )
    mistake_service.update_mistake(
        session, user_id=1, mistake_id=12, payload=MistakeUpdateIn(status="已订正")
    )
    assert mistake.my_answer_md == "旧作答"
    assert mistake.status == MistakeStatus.CORRECTED.value
    assert session.commits == 1


def test_record_review_first_correct_marks_corrected():
    mistake = _mistake()
    session = FakeSession(objects={(Question, 65): _question(), (Mistake, 12): mistake},
                          scalar_results=[None], scalars_results=[[]])
    detail = mistake_service.record_review(session, user_id=1, mistake_id=12, correct=True)
    assert mistake.correct_streak == 1
    assert mistake.status == MistakeStatus.CORRECTED.value
    assert mistake.last_review_at is not None
    assert detail.correct_streak == 1


def test_record_review_second_correct_marks_mastered():
    mistake = _mistake(status="已订正", streak=1)
    session = FakeSession(objects={(Question, 65): _question(), (Mistake, 12): mistake},
                          scalar_results=[None], scalars_results=[[]])
    mistake_service.record_review(session, user_id=1, mistake_id=12, correct=True)
    assert mistake.correct_streak == 2
    assert mistake.status == MistakeStatus.MASTERED.value


def test_record_review_wrong_resets_to_todo():
    mistake = _mistake(status="已掌握", streak=2)
    session = FakeSession(objects={(Question, 65): _question(), (Mistake, 12): mistake},
                          scalar_results=[None], scalars_results=[[]])
    before = datetime.now(timezone.utc)
    mistake_service.record_review(session, user_id=1, mistake_id=12, correct=False)
    assert mistake.correct_streak == 0
    assert mistake.status == MistakeStatus.TODO.value
    # spec §6.1：答错也要刷新复习时间，否则「待复习」排序会停在旧值。
    assert mistake.last_review_at is not None
    assert mistake.last_review_at >= before


def test_record_review_other_user_raises_404():
    session = FakeSession(objects={(Mistake, 12): _mistake(user_id=2)})
    with pytest.raises(NotFoundError):
        mistake_service.record_review(session, user_id=1, mistake_id=12, correct=True)


def test_delete_mistake_removes_analysis_too():
    mistake = _mistake()
    session = FakeSession(objects={(Mistake, 12): mistake}, scalar_results=[None])
    mistake_service.delete_mistake(session, user_id=1, mistake_id=12)
    assert mistake in session.deleted
    assert session.commits == 1


def test_delete_mistake_other_user_raises_404():
    session = FakeSession(objects={(Mistake, 12): _mistake(user_id=2)})
    with pytest.raises(NotFoundError):
        mistake_service.delete_mistake(session, user_id=1, mistake_id=12)
    assert session.commits == 0
    assert session.deleted == []


def test_stats_fills_zero_for_missing_statuses():
    session = FakeSession(
        rows_results=[
            [("已订正", 2)],                       # by_status
            [("计算失误", 1)],                     # by_cause
            [(137, "函数的单调性", 3)],            # top_kps
        ]
    )
    result = mistake_service.stats(session, user_id=1)
    assert result.total == 2
    assert {item.status: item.count for item in result.by_status} == {
        "待订正": 0, "已订正": 2, "已掌握": 0,
    }
    assert result.by_cause[0].cause_type == "计算失误"
    assert result.top_kps[0].kp_name == "函数的单调性"


def test_stats_queries_always_filter_owner():
    session = FakeSession(rows_results=[[], [], []])
    mistake_service.stats(session, user_id=7)
    for statement in session.execute_statements:
        assert "user_id" in str(statement.compile(compile_kwargs={"literal_binds": False}))


def test_stats_applies_date_range_to_all_queries():
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    end = datetime(2026, 11, 1, tzinfo=timezone.utc)
    session = FakeSession(rows_results=[[], [], []])
    mistake_service.stats(session, user_id=1, created_from=start, created_to=end)
    for statement in session.execute_statements:
        sql = str(statement.compile(compile_kwargs={"literal_binds": False}))
        # created_from/created_to 必须同时下推到三条查询（各自 >= 与 <= 各一次）。
        assert sql.count("mistakes.created_at") == 2

    plain = FakeSession(rows_results=[[], [], []])
    mistake_service.stats(plain, user_id=1)
    for statement in plain.execute_statements:
        sql = str(statement.compile(compile_kwargs={"literal_binds": False}))
        assert "created_at" not in sql


def _compiled(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": False}))


def test_build_query_always_filters_owner():
    stmt = mistake_service.build_mistakes_query(
        user_id=7, filters=mistake_service.MistakeFilters()
    )
    assert "mistakes.user_id" in _compiled(stmt)


def test_build_query_cause_filter_uses_exists_not_join():
    stmt = mistake_service.build_mistakes_query(
        user_id=1, filters=mistake_service.MistakeFilters(cause_type="计算失误")
    )
    sql = _compiled(stmt)
    assert "EXISTS" in sql.upper()
    # 只允许 JOIN questions；JOIN mistake_analyses 会因一题多条诊断放大行数。
    assert "JOIN mistake_analyses" not in sql


def test_build_query_kp_filter_uses_exists():
    stmt = mistake_service.build_mistakes_query(
        user_id=1, filters=mistake_service.MistakeFilters(kp_id=137)
    )
    sql = _compiled(stmt)
    assert "EXISTS" in sql.upper()
    assert "question_kps" in sql
    # 编译断言只保证走了 EXISTS；`@>` 的真实语义与 NULL 行为由 Task 13 真机验收覆盖。
    assert "mistake_analyses.kp_ids @>" in sql


def test_build_query_date_range_bounds():
    session_from = datetime(2026, 11, 1, tzinfo=timezone.utc)
    session_to = datetime(2026, 11, 30, tzinfo=timezone.utc)
    stmt = mistake_service.build_mistakes_query(
        user_id=1,
        filters=mistake_service.MistakeFilters(created_from=session_from, created_to=session_to),
    )
    # select(Mistake, Question) 的列清单里也有 mistakes.created_at，
    # 只看 WHERE 才能数清上下界各一次。
    where_sql = _compiled(stmt.whereclause)
    assert where_sql.count("mistakes.created_at") == 2


def test_list_mistakes_rejects_unknown_sort_field():
    session = FakeSession()
    with pytest.raises(InvalidParamError):
        mistake_service.list_mistakes(
            session,
            user_id=1,
            filters=mistake_service.MistakeFilters(),
            page=PageParams(page=1, page_size=20),
            sort=SortParams(sort_by="hack", order="desc"),
        )


def test_list_mistakes_returns_rows_with_kp_names(monkeypatch):
    mistake = _mistake()
    question = _question()
    monkeypatch.setattr(
        mistake_service,
        "paginate_sa",
        lambda session, stmt, params: type(
            "Page", (), {"items": [(mistake, question)], "total": 1, "page": 1, "size": 20}
        )(),
    )
    # d-8：一页两条批量查询——先 kp 行，再 cause_type 行（都由 execute 返回）。
    session = FakeSession(rows_results=[[(65, "函数的单调性")], []])
    data = mistake_service.list_mistakes(
        session,
        user_id=1,
        filters=mistake_service.MistakeFilters(),
        page=PageParams(page=1, page_size=20),
        sort=SortParams(),
    )
    assert data.total == 1
    assert data.items[0].kp_names == ["函数的单调性"]
    assert data.items[0].stem_excerpt.startswith("已知函数")


def test_list_mistakes_empty_page_skips_batch_queries(monkeypatch):
    monkeypatch.setattr(
        mistake_service,
        "paginate_sa",
        lambda session, stmt, params: type(
            "Page", (), {"items": [], "total": 0, "page": 1, "size": 20}
        )(),
    )
    session = FakeSession(rows_results=[[(65, "不该被查")]])
    data = mistake_service.list_mistakes(
        session,
        user_id=1,
        filters=mistake_service.MistakeFilters(),
        page=PageParams(page=1, page_size=20),
        sort=SortParams(),
    )
    assert data.items == []
    assert data.total == 0
    # 空页没有 id 可批查，KP 与诊断两条 IN 查询都不该发出。
    assert session.execute_statements == []
    assert session.rows_results == [[(65, "不该被查")]]
