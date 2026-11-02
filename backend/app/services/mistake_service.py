"""S4-2 错题服务：唯一业务入口（spec §6）。

错题是学生私有数据，所有查询显式带 user_id；他人记录一律 404，
不泄露存在性（spec D-8）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidParamError, NotFoundError
from app.models.enums import MistakeStatus
from app.models.knowledge_point import KnowledgePoint
from app.models.mistake import Mistake
from app.models.mistake_analysis import MistakeAnalysis
from app.models.question import Question
from app.models.question_kp import QuestionKp
from app.schemas.mistake import (
    MistakeAnalysisOut,
    MistakeCreateIn,
    MistakeDetailOut,
    MistakeSummaryOut,
    MistakeUpdateIn,
    OptionOut,
)

# --------------------------------------------------------------------------
# 常量区（Task 6/7 的 TASK_* / 阈值常量继续加在这里）
# --------------------------------------------------------------------------
TASK_MISTAKE_RECOGNIZE = "mistake.recognize"
MASTERY_STREAK = 2
LOW_CONFIDENCE = 0.5
EXCERPT_LEN = 120


@dataclass(frozen=True)
class MistakeFilters:
    status: str | None = None
    cause_type: str | None = None
    kp_id: int | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None


# --------------------------------------------------------------------------
# 私有辅助区（Task 6/7 的 _stats / _apply_filters 等继续加在这里）
# --------------------------------------------------------------------------
def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


def _load_owned(session: Session, *, user_id: int, mistake_id: int) -> Mistake:
    mistake = session.get(Mistake, mistake_id)
    if mistake is None or mistake.user_id != user_id:
        raise NotFoundError("错题不存在")
    return mistake


def _kp_names(session: Session, question_id: int) -> list[str]:
    rows = session.scalars(
        select(KnowledgePoint.name)
        .join(QuestionKp, QuestionKp.kp_id == KnowledgePoint.id)
        .where(QuestionKp.question_id == question_id)
        .order_by(QuestionKp.weight.desc())
    )
    return list(rows)


def _analysis_of(session: Session, mistake_id: int) -> MistakeAnalysisOut | None:
    analysis = session.scalar(
        select(MistakeAnalysis).where(MistakeAnalysis.mistake_id == mistake_id)
    )
    if analysis is None:
        return None
    return MistakeAnalysisOut(
        cause_type=analysis.cause_type,
        error_step=analysis.error_step,
        explanation_md=analysis.explanation_md,
        review_advice_md=analysis.review_advice_md,
        kp_ids=analysis.kp_ids,
        created_at=analysis.created_at,
    )


def _detail(session: Session, *, mistake: Mistake) -> MistakeDetailOut:
    question = session.get(Question, mistake.question_id)
    if question is None:
        raise NotFoundError("错题关联的题目不存在")
    options = (
        [OptionOut(**item) for item in question.options_json] if question.options_json else None
    )
    return MistakeDetailOut(
        id=mistake.id,
        question_id=mistake.question_id,
        status=mistake.status,
        correct_streak=mistake.correct_streak,
        stem_excerpt=question.stem_md[:EXCERPT_LEN],
        subject_id=question.subject_id,
        qtype=question.qtype,
        difficulty=question.difficulty,
        kp_names=_kp_names(session, mistake.question_id),
        cause_type=(analysis.cause_type if (analysis := _analysis_of(session, mistake.id)) else None),
        has_image=mistake.image_file_id is not None,
        created_at=mistake.created_at,
        last_review_at=mistake.last_review_at,
        stem_md=question.stem_md,
        options=options,
        my_answer_md=mistake.my_answer_md,
        correct_answer_md=mistake.correct_answer_md,
        image_url=(
            f"/api/v1/files/{mistake.image_file_id}/image" if mistake.image_file_id else None
        ),
        analysis=analysis,
    )


# --------------------------------------------------------------------------
# 公开函数区（Task 6/7/8 的 list / stats / review / recognize 继续加在这里）
# --------------------------------------------------------------------------
def create_from_question(
    session: Session, *, user_id: int, payload: MistakeCreateIn
) -> tuple[MistakeDetailOut, bool]:
    """题库选题录入。同 (user, question) 已存在时复用并重置（spec D-1）。"""
    question = session.get(Question, payload.question_id)
    if question is None:
        raise NotFoundError("题目不存在")
    existing = session.scalar(
        select(Mistake).where(
            Mistake.user_id == user_id, Mistake.question_id == payload.question_id
        )
    )
    answer = payload.correct_answer_md if payload.correct_answer_md is not None else question.answer_md
    if existing is not None:
        existing.status = MistakeStatus.TODO.value
        existing.correct_streak = 0
        # 录入不是复习：last_review_at 只由复习用例推进，复用重置不得改写它。
        if payload.my_answer_md is not None:
            existing.my_answer_md = payload.my_answer_md
        if answer is not None:
            existing.correct_answer_md = answer
        mistake, created = existing, False
    else:
        mistake = Mistake(
            user_id=user_id,
            question_id=payload.question_id,
            my_answer_md=payload.my_answer_md,
            correct_answer_md=answer,
            status=MistakeStatus.TODO.value,
            correct_streak=0,
        )
        session.add(mistake)
        created = True
    _commit(session)
    return _detail(session, mistake=mistake), created


def get_detail(session: Session, *, user_id: int, mistake_id: int) -> MistakeDetailOut:
    return _detail(session, mistake=_load_owned(session, user_id=user_id, mistake_id=mistake_id))


def update_mistake(
    session: Session, *, user_id: int, mistake_id: int, payload: MistakeUpdateIn
) -> MistakeDetailOut:
    mistake = _load_owned(session, user_id=user_id, mistake_id=mistake_id)
    if payload.my_answer_md is not None:
        mistake.my_answer_md = payload.my_answer_md
    if payload.correct_answer_md is not None:
        mistake.correct_answer_md = payload.correct_answer_md
    if payload.status is not None:
        mistake.status = payload.status
    _commit(session)
    return _detail(session, mistake=mistake)