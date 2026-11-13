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