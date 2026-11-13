"""S5-4 判分纯函数：单选/多选自动、填空/解答自评、覆盖校验。"""
from __future__ import annotations

import pytest

from app.core.exceptions import ConflictError, InvalidParamError
from app.schemas.answer import AnswerSubmitItemIn
from app.schemas.paper import OptionOut, PaperItemOut
from app.services import answer_service
from app.services.answer_service import AnswerInput


def _item(
    question_id: int = 501,
    *,
    qtype: str = "单选",
    answer: str | None = "A",
    score: int = 3,
    kp_ids: list[int] | None = None,
) -> PaperItemOut:
    return PaperItemOut(
        question_id=question_id,
        qtype=qtype,
        difficulty=3,
        score=score,
        kp_ids=kp_ids if kp_ids is not None else [117],
        parts=None,
        subject_id=7,
        stem_md="题干",
        options=[OptionOut(key="A", text="A"), OptionOut(key="B", text="B")],
        answer_md=answer,
        analysis_md=None,
        verified=True,
        origin="exam",
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a", {"A"}),
        ("Ａ", {"A"}),
        ("A,C", {"A", "C"}),
        ("c a", {"A", "C"}),
        ("CA", {"A", "C"}),
        (None, set()),
        ("", set()),
    ],
)
def test_normalize_choice(raw, expected):
    assert answer_service.normalize_choice(raw) == frozenset(expected)


def test_single_choice_auto_grade():
    assert answer_service.grade_objective("单选", "A", "a") is True
    assert answer_service.grade_objective("单选", "A", "B") is False
    assert answer_service.grade_objective("单选", "A", "AB") is False
    assert answer_service.grade_objective("单选", "A", None) is False


def test_multiple_choice_auto_grade_order_insensitive():
    assert answer_service.grade_objective("多选", "AC", "CA") is True
    assert answer_service.grade_objective("多选", "AC", "A,C") is True
    assert answer_service.grade_objective("多选", "AC", "A") is False
    assert answer_service.grade_objective("多选", "AC", "ABC") is False
    assert answer_service.grade_objective("多选", "AC", "") is False


def test_grade_objective_item_scores_full_or_zero():
    correct = answer_service.grade_item(_item(), AnswerInput(question_id=501, user_answer_md="a"))
    assert correct.is_correct is True
    assert float(correct.score) == 3.0
    assert correct.self_rated == 1.0
    wrong = answer_service.grade_item(_item(), AnswerInput(question_id=501, user_answer_md="B"))
    assert wrong.is_correct is False
    assert float(wrong.score) == 0.0
    assert wrong.self_rated == 0.0


def test_self_rated_item_half_credit():
    item = _item(qtype="解答", answer="x=1", score=8)
    graded = answer_service.grade_item(
        item, AnswerInput(question_id=501, user_answer_md="x=1", self_rated=0.5)
    )
    assert float(graded.score) == 4.0
    assert graded.is_correct is False
    assert graded.self_rated == 0.5


def test_self_rated_missing_is_conflict():
    with pytest.raises(ConflictError):
        answer_service.grade_item(
            _item(qtype="填空"), AnswerInput(question_id=501, user_answer_md="1")
        )


@pytest.mark.parametrize("value", [0.7, -0.5, 2.0])
def test_self_rated_illegal_value_422(value):
    with pytest.raises(InvalidParamError):
        answer_service.validate_self_rated(value)


@pytest.mark.parametrize("value", [0, 0.5, 1, 0.0, 1.0])
def test_self_rated_allowed_values(value):
    assert answer_service.validate_self_rated(value) == float(value)


def test_build_answer_map_rejects_duplicate_and_unknown():
    items = [_item(501), _item(502)]
    with pytest.raises(InvalidParamError):
        answer_service.build_answer_map(
            items,
            [
                AnswerSubmitItemIn(question_id=501),
                AnswerSubmitItemIn(question_id=501),
            ],
        )
    with pytest.raises(InvalidParamError):
        answer_service.build_answer_map(items, [AnswerSubmitItemIn(question_id=999)])


def test_build_answer_map_requires_every_question():
    items = [_item(501), _item(502)]
    with pytest.raises(InvalidParamError):
        answer_service.build_answer_map(items, [AnswerSubmitItemIn(question_id=501)])


def test_build_answer_map_keeps_self_rating_and_time():
    items = [_item(501, qtype="解答", score=8)]
    mapping = answer_service.build_answer_map(
        items,
        [
            AnswerSubmitItemIn(
                question_id=501, user_answer_md="x=1", self_rated=0.5, time_spent_sec=42
            )
        ],
    )
    assert mapping[501].self_rated == 0.5
    assert mapping[501].time_spent_sec == 42


def test_missing_self_ratings_lists_blank_and_solution_only():
    items = [
        _item(501, qtype="单选"),
        _item(502, qtype="填空"),
        _item(503, qtype="解答", score=8),
    ]
    answers = {
        501: AnswerInput(question_id=501, user_answer_md="A"),
        502: AnswerInput(question_id=502, user_answer_md="1"),
        503: AnswerInput(question_id=503, user_answer_md="x=1", self_rated=1.0),
    }
    assert answer_service.missing_self_ratings(items, answers) == [502]


def test_grade_paper_sums_and_keeps_order():
    items = [_item(501, qtype="单选", score=3), _item(502, qtype="解答", score=8)]
    answers = {
        501: AnswerInput(question_id=501, user_answer_md="A"),
        502: AnswerInput(question_id=502, user_answer_md="x=1", self_rated=0.5),
    }
    graded = answer_service.grade_paper(items, answers)
    assert [row.question_id for row in graded] == [501, 502]
    assert answer_service.total_score(graded) == 7.0

# ---------- 编排用例（fake session，不连库） ----------

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.answer import Answer
from app.models.enums import PaperStatus
from app.models.mastery import Mastery
from app.models.mistake import Mistake
from app.schemas.answer import AnswerRowOut, AnswerSubmitItemIn, PaperAnswersOut, PaperSubmitOut
from app.schemas.paper import PaperDetailOut


class _Rows(list):
    def all(self):
        return list(self)


class _ExecResult:
    rowcount = 1

    def all(self):
        return []


class FakeSession:
    """按调用顺序吐 scalars 结果；记录 commit/rollback 次数。"""

    def __init__(self, *, papers=(), scalars=()):
        self.papers = list(papers)
        self.scalars_results = list(scalars)
        self.scalar_results: list[object | None] = []
        self.get_calls: list[tuple[object, object]] = []
        self.scalar_statements: list[object] = []
        self.executed: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0

    def get(self, model, pk):
        self.get_calls.append((model, pk))
        if getattr(model, "__tablename__", None) == "papers":
            for paper in self.papers:
                if getattr(paper, "id", None) == pk:
                    return paper
        return None

    def scalars(self, statement):
        self.scalar_statements.append(statement)
        return _Rows(self.scalars_results.pop(0))

    def scalar(self, statement):
        self.scalar_statements.append(statement)
        return self.scalar_results.pop(0)

    def execute(self, statement):
        self.executed.append(statement)
        return _ExecResult()

    def add(self, row):
        return None

    def flush(self):
        self.flushes += 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _paper(status: str = PaperStatus.GENERATED.value) -> SimpleNamespace:
    return SimpleNamespace(id=8, user_id=50, status=status)


def _detail(items, *, status: str = PaperStatus.GENERATED.value) -> PaperDetailOut:
    return PaperDetailOut(
        id=8,
        title="验收卷",
        status=status,
        total_score=sum(item.score for item in items),
        duration_min=60,
        question_ids=[item.question_id for item in items],
        created_at="2026-11-13T08:00:00+00:00",
        constraint_json={},
        items=items,
        missing_question_ids=[],
    )


def test_get_answers_fills_missing_rows(monkeypatch):
    items = [_item(501), _item(502, qtype="解答", score=8)]
    monkeypatch.setattr(answer_service.paper_plan_service, "get_paper", lambda *a, **k: _detail(items))
    saved = Answer(
        id=1,
        user_id=50,
        paper_id=8,
        question_id=501,
        user_answer_md="A",
        is_correct=True,
        score=Decimal("3.00"),
        self_rated=Decimal("1.0"),
        time_spent_sec=9,
    )
    session = FakeSession(scalars=[[saved]])
    out = answer_service.get_answers(session, user_id=50, paper_id=8)
    assert isinstance(out, PaperAnswersOut)
    assert [row.question_id for row in out.items] == [501, 502]
    assert out.items[0].saved is True
    assert out.items[0].score == 3.0
    assert out.items[1].saved is False and out.items[1].user_answer_md is None
    assert out.earned_score == 3.0
    assert out.submitted is False


def test_get_answers_reports_submitted_and_earned(monkeypatch):
    items = [_item(501)]
    monkeypatch.setattr(
        answer_service.paper_plan_service,
        "get_paper",
        lambda *a, **k: _detail(items, status=PaperStatus.SUBMITTED.value),
    )
    saved = Answer(
        id=1,
        user_id=50,
        paper_id=8,
        question_id=501,
        user_answer_md="A",
        is_correct=True,
        score=Decimal("3.00"),
        self_rated=Decimal("1.0"),
        time_spent_sec=9,
    )
    out = answer_service.get_answers(FakeSession(scalars=[[saved]]), user_id=50, paper_id=8)
    assert out.submitted is True
    assert out.earned_score == 3.0


def test_save_answer_upserts_and_returns_row():
    paper = _paper()
    session = FakeSession(papers=[paper], scalars=[])
    session.scalar_results = [
        Answer(
            id=1,
            user_id=50,
            paper_id=8,
            question_id=501,
            user_answer_md="A",
            time_spent_sec=12,
        )
    ]
    # 先 get_paper，再 get(Paper)；monkeypatch get_paper 返回 detail
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            answer_service.paper_plan_service,
            "get_paper",
            lambda *a, **k: _detail([_item(501)]),
        )
        out = answer_service.save_answer(
            session,
            user_id=50,
            paper_id=8,
            question_id=501,
            payload=answer_service.AnswerSaveIn(user_answer_md="A", time_spent_sec=12),
        )
    assert isinstance(out, AnswerRowOut)
    assert out.saved is True and out.user_answer_md == "A"
    assert session.executed, "应执行 upsert"
    assert session.commits == 0, "草稿不提交，由路由统一提交"


def test_save_answer_rejects_submitted_paper(monkeypatch):
    items = [_item(501)]
    monkeypatch.setattr(
        answer_service.paper_plan_service,
        "get_paper",
        lambda *a, **k: _detail(items, status=PaperStatus.SUBMITTED.value),
    )
    session = FakeSession(papers=[_paper(PaperStatus.SUBMITTED.value)])
    with pytest.raises(ConflictError, match="已提交"):
        answer_service.save_answer(
            session,
            user_id=50,
            paper_id=8,
            question_id=501,
            payload=answer_service.AnswerSaveIn(user_answer_md="A"),
        )
    assert session.executed == []


def test_save_answer_rejects_question_not_in_paper(monkeypatch):
    monkeypatch.setattr(
        answer_service.paper_plan_service,
        "get_paper",
        lambda *a, **k: _detail([_item(501)]),
    )
    session = FakeSession(papers=[_paper()])
    with pytest.raises(NotFoundError):
        answer_service.save_answer(
            session,
            user_id=50,
            paper_id=8,
            question_id=999,
            payload=answer_service.AnswerSaveIn(user_answer_md="A"),
        )


def test_submit_paper_orchestrates_transaction(monkeypatch):
    items = [_item(501, qtype="单选", score=3), _item(502, qtype="解答", score=8)]
    paper = _paper()
    session = FakeSession(
        papers=[paper],
        scalars=[[], [], []],
    )
    session.scalar_results = [paper]

    record_calls: list[dict] = []
    monkeypatch.setattr(
        answer_service.paper_plan_service, "get_paper", lambda *a, **k: _detail(items)
    )

    def fake_record_attempts(session, **kwargs):
        record_calls.append(kwargs)
        row = Mastery(
            user_id=50,
            kp_id=kwargs["kp_ids"][0],
            mastery=Decimal("0.117"),
            attempts=1,
            correct_cnt=1,
            stability=Decimal("2.00"),
        )
        return [row]

    monkeypatch.setattr(answer_service.mastery_service, "record_attempts", fake_record_attempts)

    mistake_calls: list[dict] = []

    def fake_record_wrong(session, **kwargs):
        mistake_calls.append(kwargs)
        return Mistake(id=kwargs["question_id"], user_id=50, question_id=kwargs["question_id"], status="待订正")

    monkeypatch.setattr(answer_service.mistake_service, "record_wrong_answer", fake_record_wrong)

    out = answer_service.submit_paper(
        session,
        user_id=50,
        paper_id=8,
        items=[
            AnswerSubmitItemIn(question_id=501, user_answer_md="A"),
            AnswerSubmitItemIn(question_id=502, user_answer_md="x=1", self_rated=1),
        ],
    )

    assert isinstance(out, PaperSubmitOut)
    assert out.score == 11.0
    assert out.correct_count == 2
    assert out.question_count == 2
    assert out.mistake_question_ids == []
    assert mistake_calls == [], "满分不入错题"
    assert [call["s"] for call in record_calls] == [1.0, 1.0]
    assert [call["difficulty"] for call in record_calls] == [3, 3]
    assert session.commits == 1
    assert session.rollbacks == 0
    assert paper.status == PaperStatus.SUBMITTED.value


def test_submit_paper_marks_wrong_answers(monkeypatch):
    items = [_item(501, qtype="单选", score=3), _item(502, qtype="解答", score=8)]
    paper = _paper()
    session = FakeSession(papers=[paper], scalars=[[], [], []])
    session.scalar_results = [paper]
    monkeypatch.setattr(
        answer_service.paper_plan_service, "get_paper", lambda *a, **k: _detail(items)
    )
    monkeypatch.setattr(
        answer_service.mastery_service,
        "record_attempts",
        lambda *a, **k: [Mastery(user_id=50, kp_id=117, mastery=Decimal("0.1"), attempts=1,
                                correct_cnt=0, stability=Decimal("2.00"))],
    )
    mistake_calls: list[dict] = []

    def fake_record_wrong(session, **kwargs):
        mistake_calls.append(kwargs)
        return Mistake(id=kwargs["question_id"], user_id=50, question_id=kwargs["question_id"], status="待订正")

    monkeypatch.setattr(answer_service.mistake_service, "record_wrong_answer", fake_record_wrong)
    out = answer_service.submit_paper(
        session,
        user_id=50,
        paper_id=8,
        items=[
            AnswerSubmitItemIn(question_id=501, user_answer_md="B"),
            AnswerSubmitItemIn(question_id=502, user_answer_md="x=2", self_rated=0.5),
        ],
    )
    assert out.score == 4.0
    assert out.correct_count == 0
    assert sorted(out.mistake_question_ids) == [501, 502]
    assert {call["question_id"] for call in mistake_calls} == {501, 502}
    assert mistake_calls[0]["my_answer_md"] in {"B", "x=2"}
    assert session.commits == 1


def test_submit_paper_rejects_missing_self_rating(monkeypatch):
    items = [_item(502, qtype="解答", score=8)]
    session = FakeSession(papers=[_paper()], scalars=[])
    session.scalar_results = [_paper()]
    monkeypatch.setattr(
        answer_service.paper_plan_service, "get_paper", lambda *a, **k: _detail(items)
    )
    with pytest.raises(ConflictError, match="1 道题未自评"):
        answer_service.submit_paper(
            session,
            user_id=50,
            paper_id=8,
            items=[AnswerSubmitItemIn(question_id=502, user_answer_md="x=1")],
        )
    assert session.commits == 0
    assert session.executed == []


def test_submit_paper_rejects_duplicate_submission(monkeypatch):
    items = [_item(501)]
    monkeypatch.setattr(
        answer_service.paper_plan_service,
        "get_paper",
        lambda *a, **k: _detail(items, status=PaperStatus.SUBMITTED.value),
    )
    session = FakeSession(papers=[_paper(PaperStatus.SUBMITTED.value)])
    with pytest.raises(ConflictError, match="请勿重复交卷"):
        answer_service.submit_paper(
            session,
            user_id=50,
            paper_id=8,
            items=[AnswerSubmitItemIn(question_id=501, user_answer_md="A")],
        )
    assert session.scalar_statements == [], "校验失败前不开行锁"


def test_submit_paper_locks_row_before_writes(monkeypatch):
    items = [_item(501)]
    paper = _paper()
    session = FakeSession(papers=[paper], scalars=[[], [], []])
    session.scalar_results = [paper]
    monkeypatch.setattr(
        answer_service.paper_plan_service, "get_paper", lambda *a, **k: _detail(items)
    )
    monkeypatch.setattr(
        answer_service.mastery_service,
        "record_attempts",
        lambda *a, **k: [Mastery(user_id=50, kp_id=117, mastery=Decimal("0.1"), attempts=1,
                                correct_cnt=1, stability=Decimal("2.00"))],
    )
    answer_service.submit_paper(
        session,
        user_id=50,
        paper_id=8,
        items=[AnswerSubmitItemIn(question_id=501, user_answer_md="A")],
    )
    locked = session.scalar_statements[0]
    assert "FOR UPDATE" in str(locked)
