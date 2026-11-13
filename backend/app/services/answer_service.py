"""S5-4 在线作答：判分纯函数 + 草稿读写 + 交卷单事务（API.md §8）。

判分口径（spec D-2/D-7）：单选、多选自动判分；填空、解答由学生自评 0/0.5/1，
得分 = 题分 × 自评。交卷把答案、掌握度、错题、试卷状态放进同一个事务。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import unicodedata
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ForbiddenError, InvalidParamError, NotFoundError
from app.models.answer import Answer
from app.models.enums import PaperStatus
from app.models.knowledge_point import KnowledgePoint
from app.models.mastery import Mastery
from app.models.paper import Paper
from app.schemas.answer import (
    AnswerRowOut,
    AnswerSaveIn,
    AnswerSubmitItemIn,
    GradedItemOut,
    MasteryDeltaOut,
    PaperAnswersOut,
    PaperBriefOut,
    PaperSubmitOut,
)
from app.schemas.paper import PaperDetailOut, PaperItemOut
from app.services import mastery_service, mistake_service, paper_plan_service

AUTO_QTYPES = ("单选", "多选")
SELF_RATED_QTYPES = ("填空", "解答")
ALLOWED_SELF_RATINGS = (0.0, 0.5, 1.0)
SCORE_PRECISION = 2
CHOICE_LETTERS = "ABCDEFGH"


@dataclass(frozen=True)
class AnswerInput:
    question_id: int
    user_answer_md: str | None = None
    self_rated: float | None = None
    time_spent_sec: int | None = None


@dataclass(frozen=True)
class GradedItem:
    question_id: int
    qtype: str
    is_correct: bool
    score: float
    self_rated: float | None
    user_answer_md: str | None


def normalize_choice(value: str | None) -> frozenset[str]:
    """选项字母归一化：全半角、大小写、逗号/空格、顺序都不影响比较。"""
    if not value:
        return frozenset()
    letters: set[str] = set()
    for raw in unicodedata.normalize("NFKC", value):
        if raw in ",，、;；/| \t\r\n":
            continue
        char = raw.strip().upper()
        if char and char in CHOICE_LETTERS:
            letters.add(char)
    return frozenset(letters)


def validate_self_rated(value: Any) -> float:
    try:
        rated = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidParamError("self_rated 只能是 0 / 0.5 / 1") from exc
    if rated not in ALLOWED_SELF_RATINGS:
        raise InvalidParamError("self_rated 只能是 0 / 0.5 / 1")
    return rated


def grade_objective(qtype: str, answer_md: str | None, user_answer_md: str | None) -> bool:
    expected = normalize_choice(answer_md)
    if not expected or not user_answer_md:
        return False
    actual = normalize_choice(user_answer_md)
    if qtype == "单选":
        return len(actual) == 1 and actual == expected
    return actual == expected


def grade_item(item: PaperItemOut, answer: AnswerInput) -> GradedItem:
    if item.qtype in AUTO_QTYPES:
        correct = grade_objective(item.qtype, item.answer_md, answer.user_answer_md)
        rated = 1.0 if correct else 0.0
        score = float(item.score) if correct else 0.0
    elif item.qtype in SELF_RATED_QTYPES:
        if answer.self_rated is None:
            raise ConflictError("还有 1 道题未自评")
        rated = validate_self_rated(answer.self_rated)
        score = round(float(item.score) * rated, SCORE_PRECISION)
        correct = rated == 1.0
    else:
        raise InvalidParamError(f"未知题型：{item.qtype}")
    return GradedItem(
        question_id=item.question_id,
        qtype=item.qtype,
        is_correct=correct,
        score=score,
        self_rated=rated,
        user_answer_md=answer.user_answer_md,
    )


def build_answer_map(
    items: Sequence[PaperItemOut], payload: Sequence[AnswerSubmitItemIn]
) -> dict[int, AnswerInput]:
    item_ids = {item.question_id for item in items}
    seen: set[int] = set()
    mapping: dict[int, AnswerInput] = {}
    for row in payload:
        if row.question_id not in item_ids:
            raise InvalidParamError("题目不属于该试卷")
        if row.question_id in seen:
            raise InvalidParamError(f"题目重复提交：{row.question_id}")
        seen.add(row.question_id)
        rated = validate_self_rated(row.self_rated) if row.self_rated is not None else None
        mapping[row.question_id] = AnswerInput(
            question_id=row.question_id,
            user_answer_md=row.user_answer_md,
            self_rated=rated,
            time_spent_sec=row.time_spent_sec,
        )
    missing = item_ids - seen
    if missing:
        raise InvalidParamError(f"缺少 {len(missing)} 道题的作答")
    return mapping


def missing_self_ratings(
    items: Sequence[PaperItemOut], answers: Mapping[int, AnswerInput]
) -> list[int]:
    return [
        item.question_id
        for item in items
        if item.qtype in SELF_RATED_QTYPES
        and answers[item.question_id].self_rated is None
    ]


def grade_paper(
    items: Sequence[PaperItemOut], answers: Mapping[int, AnswerInput]
) -> list[GradedItem]:
    return [grade_item(item, answers[item.question_id]) for item in items]


def total_score(graded: Sequence[GradedItem]) -> float:
    return round(sum(row.score for row in graded), SCORE_PRECISION)


def _paper_detail(session: Session, *, user_id: int, paper_id: int) -> PaperDetailOut:
    return paper_plan_service.get_paper(session, user_id=user_id, paper_id=paper_id)


def _row_out(row: Answer | None, *, question_id: int) -> AnswerRowOut:
    if row is None:
        return AnswerRowOut(
            question_id=question_id,
            user_answer_md=None,
            self_rated=None,
            is_correct=None,
            score=None,
            time_spent_sec=None,
            saved=False,
        )
    return AnswerRowOut(
        question_id=question_id,
        user_answer_md=row.user_answer_md,
        self_rated=float(row.self_rated) if row.self_rated is not None else None,
        is_correct=row.is_correct,
        score=float(row.score) if row.score is not None else None,
        time_spent_sec=row.time_spent_sec,
        saved=True,
    )


def get_answers(session: Session, *, user_id: int, paper_id: int) -> PaperAnswersOut:
    detail = _paper_detail(session, user_id=user_id, paper_id=paper_id)
    question_ids = [item.question_id for item in detail.items]
    rows = (
        session.scalars(
            select(Answer).where(
                Answer.user_id == user_id,
                Answer.paper_id == paper_id,
                Answer.question_id.in_(question_ids),
            )
        ).all()
        if question_ids
        else []
    )
    by_question = {row.question_id: row for row in rows}
    earned = sum(
        float(row.score) for row in rows if row.score is not None and row.question_id in by_question
    )
    return PaperAnswersOut(
        paper=PaperBriefOut(
            id=detail.id,
            title=detail.title,
            status=detail.status,
            total_score=detail.total_score,
        ),
        items=[
            _row_out(by_question.get(question_id), question_id=question_id)
            for question_id in question_ids
        ],
        submitted=detail.status == PaperStatus.SUBMITTED.value,
        earned_score=round(earned, SCORE_PRECISION),
    )


def _ensure_editable(paper: Paper) -> None:
    if paper.status == PaperStatus.SUBMITTED.value:
        raise ConflictError("试卷已提交，不能再修改答案")


def save_answer(
    session: Session, *, user_id: int, paper_id: int, question_id: int, payload: AnswerSaveIn
) -> AnswerRowOut:
    detail = _paper_detail(session, user_id=user_id, paper_id=paper_id)
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise NotFoundError("试卷不存在")
    if paper.user_id != user_id:
        raise ForbiddenError("无权访问该试卷")
    _ensure_editable(paper)
    if question_id not in {item.question_id for item in detail.items}:
        raise NotFoundError("题目不属于该试卷")

    values = {
        "user_id": user_id,
        "question_id": question_id,
        "paper_id": paper_id,
        "user_answer_md": payload.user_answer_md,
        "time_spent_sec": payload.time_spent_sec,
    }
    stmt = pg_insert(Answer).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Answer.user_id, Answer.paper_id, Answer.question_id],
        index_where=Answer.paper_id.is_not(None),
        set_={
            "user_answer_md": stmt.excluded.user_answer_md,
            "time_spent_sec": stmt.excluded.time_spent_sec,
        },
    )
    session.execute(stmt)
    session.flush()
    row = session.scalar(
        select(Answer).where(
            Answer.user_id == user_id,
            Answer.paper_id == paper_id,
            Answer.question_id == question_id,
        )
    )
    return _row_out(row, question_id=question_id)


def _upsert_graded_answer(
    session: Session,
    *,
    user_id: int,
    paper_id: int,
    graded: GradedItem,
    time_spent_sec: int | None,
) -> None:
    stmt = pg_insert(Answer).values(
        user_id=user_id,
        question_id=graded.question_id,
        paper_id=paper_id,
        user_answer_md=graded.user_answer_md,
        is_correct=graded.is_correct,
        score=Decimal(str(graded.score)),
        self_rated=Decimal(str(graded.self_rated)) if graded.self_rated is not None else None,
        time_spent_sec=time_spent_sec,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Answer.user_id, Answer.paper_id, Answer.question_id],
        index_where=Answer.paper_id.is_not(None),
        set_={
            "user_answer_md": stmt.excluded.user_answer_md,
            "is_correct": stmt.excluded.is_correct,
            "score": stmt.excluded.score,
            "self_rated": stmt.excluded.self_rated,
            "time_spent_sec": stmt.excluded.time_spent_sec,
        },
    )
    session.execute(stmt)


def _mastery_deltas(
    *,
    before: Mapping[int, Mastery],
    after: Mapping[int, Mastery],
    names: Mapping[int, str],
    touched: Sequence[int],
) -> list[MasteryDeltaOut]:
    deltas: list[MasteryDeltaOut] = []
    for kp_id in sorted({int(value) for value in touched}):
        after_row = after.get(kp_id)
        if after_row is None:
            continue
        before_row = before.get(kp_id)
        before_value = float(before_row.mastery) if before_row is not None else None
        deltas.append(
            MasteryDeltaOut(
                kp_id=kp_id,
                kp_name=names.get(kp_id) or f"知识点 #{kp_id}",
                mastery_before=before_value,
                mastery_after=float(after_row.mastery),
                attempts_delta=after_row.attempts - (before_row.attempts if before_row else 0),
            )
        )
    return deltas


def _touched_kp_ids(graded: Sequence[GradedItem], items: Sequence[PaperItemOut]) -> set[int]:
    by_question = {item.question_id: item for item in items}
    return {
        int(kp_id)
        for row in graded
        for kp_id in by_question[row.question_id].kp_ids
    }


def _kp_names(session: Session, kp_ids: Sequence[int]) -> dict[int, str]:
    if not kp_ids:
        return {}
    rows = session.execute(
        select(KnowledgePoint.id, KnowledgePoint.name).where(KnowledgePoint.id.in_(kp_ids))
    ).all()
    return {int(row.id): row.name for row in rows}


def _wrong_question_ids(
    graded: Sequence[GradedItem], items: Sequence[PaperItemOut]
) -> list[int]:
    by_question = {item.question_id: item for item in items}
    return [
        row.question_id
        for row in graded
        if row.score < float(by_question[row.question_id].score)
        and (row.user_answer_md or "").strip()
    ]


def submit_paper(
    session: Session, *, user_id: int, paper_id: int, items: Sequence[AnswerSubmitItemIn]
) -> PaperSubmitOut:
    detail = _paper_detail(session, user_id=user_id, paper_id=paper_id)
    if detail.status == PaperStatus.SUBMITTED.value:
        raise ConflictError("试卷已提交，请勿重复交卷")
    paper = session.scalar(
        select(Paper).where(Paper.id == paper_id).with_for_update()
    )
    if paper is None:
        raise NotFoundError("试卷不存在")
    if paper.user_id != user_id:
        raise ForbiddenError("无权访问该试卷")
    if paper.status == PaperStatus.SUBMITTED.value:
        raise ConflictError("试卷已提交，请勿重复交卷")

    answers = build_answer_map(detail.items, items)
    missing = missing_self_ratings(detail.items, answers)
    if missing:
        raise ConflictError(f"还有 {len(missing)} 道题未自评")
    graded = grade_paper(detail.items, answers)
    touched = sorted(_touched_kp_ids(graded, detail.items))
    before_rows = (
        {
            row.kp_id: row
            for row in session.scalars(
                select(Mastery).where(Mastery.user_id == user_id, Mastery.kp_id.in_(touched))
            )
        }
        if touched
        else {}
    )

    for item, row in zip(detail.items, graded):
        _upsert_graded_answer(
            session,
            user_id=user_id,
            paper_id=paper_id,
            graded=row,
            time_spent_sec=answers[item.question_id].time_spent_sec,
        )
        mastery_service.record_attempts(
            session,
            user_id=user_id,
            kp_ids=item.kp_ids,
            s=row.self_rated if row.self_rated is not None else 0.0,
            difficulty=item.difficulty,
        )
    session.flush()

    mistake_ids: list[int] = []
    for question_id in _wrong_question_ids(graded, detail.items):
        mistake = mistake_service.record_wrong_answer(
            session,
            user_id=user_id,
            question_id=question_id,
            my_answer_md=answers[question_id].user_answer_md,
            correct_answer_md={item.question_id: item.answer_md for item in detail.items}[
                question_id
            ],
        )
        mistake_ids.append(int(mistake.id))

    after_rows = (
        {
            row.kp_id: row
            for row in session.scalars(
                select(Mastery).where(Mastery.user_id == user_id, Mastery.kp_id.in_(touched))
            )
        }
        if touched
        else {}
    )
    names = _kp_names(session, touched)
    paper.status = PaperStatus.SUBMITTED.value
    result = PaperSubmitOut(
        paper_id=paper_id,
        score=total_score(graded),
        total_score=detail.total_score,
        correct_count=sum(1 for row in graded if row.is_correct),
        question_count=len(graded),
        elapsed_sec=sum(value or 0 for value in (answer.time_spent_sec for answer in answers.values())),
        items=[
            GradedItemOut(
                question_id=row.question_id,
                qtype=row.qtype,
                is_correct=row.is_correct,
                score=row.score,
                self_rated=row.self_rated,
                user_answer_md=row.user_answer_md,
            )
            for row in graded
        ],
        mastery=_mastery_deltas(
            before=before_rows,
            after=after_rows,
            names=names,
            touched=touched,
        ),
        mistake_question_ids=mistake_ids,
        missing_question_ids=list(detail.missing_question_ids),
    )
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return result