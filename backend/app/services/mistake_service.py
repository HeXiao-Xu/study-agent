"""S4-2 错题服务：唯一业务入口（spec §6）。

错题是学生私有数据，所有查询显式带 user_id；他人记录一律 404，
不泄露存在性（spec D-8）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi_pagination import Params
from fastapi_pagination.ext.sqlalchemy import paginate as paginate_sa
from sqlalchemy import Select, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, InvalidParamError, NotFoundError
from app.models.enums import MISTAKE_STATUSES, MistakeStatus
from app.models.knowledge_point import KnowledgePoint
from app.models.mistake import Mistake
from app.models.mistake_analysis import MistakeAnalysis
from app.models.question import Question
from app.models.question_kp import QuestionKp
from app.schemas.common import PageData
from app.schemas.mistake import (
    CauseCountOut,
    KpCountOut,
    MistakeAnalysisOut,
    MistakeCreateIn,
    MistakeDetailOut,
    MistakeStatsOut,
    MistakeSummaryOut,
    MistakeUpdateIn,
    OptionOut,
    StatusCountOut,
)
from app.utils.pagination import PageParams, SortParams, apply_sort

# --------------------------------------------------------------------------
# 常量区（Task 6/7 的 TASK_* / 阈值常量继续加在这里）
# --------------------------------------------------------------------------
TASK_MISTAKE_RECOGNIZE = "mistake.recognize"
MASTERY_STREAK = 2
LOW_CONFIDENCE = 0.5
EXCERPT_LEN = 120
SORTABLE: dict[str, object] = {
    "created_at": Mistake.created_at,
    "last_review_at": Mistake.last_review_at,
    "status": Mistake.status,
    "correct_streak": Mistake.correct_streak,
}


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


def _reset_reentry(mistake: Mistake, *, payload: MistakeCreateIn, answer: str | None) -> None:
    """复用并重置（spec D-1）：录入不是复习，last_review_at 只由复习用例推进。

    新建分支因并发撞唯一约束后也复用它，保证「复用」只有这一处定义。
    """
    mistake.status = MistakeStatus.TODO.value
    mistake.correct_streak = 0
    if payload.my_answer_md is not None:
        mistake.my_answer_md = payload.my_answer_md
    if answer is not None:
        mistake.correct_answer_md = answer


def _detail(session: Session, *, mistake: Mistake) -> MistakeDetailOut:
    question = session.get(Question, mistake.question_id)
    if question is None:
        raise NotFoundError("错题关联的题目不存在")
    options = (
        [OptionOut(**item) for item in question.options_json] if question.options_json else None
    )
    analysis = _analysis_of(session, mistake.id)
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
        cause_type=analysis.cause_type if analysis else None,
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
        _reset_reentry(existing, payload=payload, answer=answer)
        mistake, created = existing, False
        _commit(session)
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
        try:
            _commit(session)
        except IntegrityError:
            # 并发录入同一 (user, question)：唯一约束的赢家是另一请求已提交的行，
            # _commit 已回滚。重查后按 D-1 复用，IntegrityError 不能冒到路由层变 500。
            winner = session.scalar(
                select(Mistake).where(
                    Mistake.user_id == user_id, Mistake.question_id == payload.question_id
                )
            )
            if winner is None:
                raise ConflictError("错题录入冲突，请重试") from None
            _reset_reentry(winner, payload=payload, answer=answer)
            mistake, created = winner, False
            _commit(session)
        else:
            created = True
    return _detail(session, mistake=mistake), created


def get_detail(session: Session, *, user_id: int, mistake_id: int) -> MistakeDetailOut:
    return _detail(session, mistake=_load_owned(session, user_id=user_id, mistake_id=mistake_id))


def update_mistake(
    session: Session, *, user_id: int, mistake_id: int, payload: MistakeUpdateIn
) -> MistakeDetailOut:
    mistake = _load_owned(session, user_id=user_id, mistake_id=mistake_id)
    # 与 S4-1 PATCH 同口径：显式传 null = 清空可空列，未传 = 保持原值。
    fields = payload.model_fields_set
    if "my_answer_md" in fields:
        mistake.my_answer_md = payload.my_answer_md
    if "correct_answer_md" in fields:
        mistake.correct_answer_md = payload.correct_answer_md
    if "status" in fields and payload.status is not None:
        mistake.status = payload.status
    _commit(session)
    return _detail(session, mistake=mistake)


def record_review(
    session: Session, *, user_id: int, mistake_id: int, correct: bool
) -> MistakeDetailOut:
    """复习结果驱动状态机（spec §6.1）：连续答对 MASTERY_STREAK 次算掌握。"""
    mistake = _load_owned(session, user_id=user_id, mistake_id=mistake_id)
    if correct:
        mistake.correct_streak += 1
        mistake.status = (
            MistakeStatus.MASTERED.value
            if mistake.correct_streak >= MASTERY_STREAK
            else MistakeStatus.CORRECTED.value
        )
    else:
        mistake.correct_streak = 0
        mistake.status = MistakeStatus.TODO.value
    mistake.last_review_at = datetime.now(timezone.utc)
    _commit(session)
    return _detail(session, mistake=mistake)


def delete_mistake(session: Session, *, user_id: int, mistake_id: int) -> None:
    """硬删；诊断行同事务删掉，不留孤儿（spec D-12）。"""
    mistake = _load_owned(session, user_id=user_id, mistake_id=mistake_id)
    analysis = session.scalar(
        select(MistakeAnalysis).where(MistakeAnalysis.mistake_id == mistake_id)
    )
    if analysis is not None:
        session.delete(analysis)
        session.flush()
    session.delete(mistake)
    _commit(session)


def stats(
    session: Session,
    *,
    user_id: int,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> MistakeStatsOut:
    """三个维度的 SQL 聚合（spec D-10）；缺的状态补 0，前端不用自己做占位。"""
    base_where = [Mistake.user_id == user_id]
    if created_from is not None:
        base_where.append(Mistake.created_at >= created_from)
    if created_to is not None:
        base_where.append(Mistake.created_at <= created_to)

    status_rows = session.execute(
        select(Mistake.status, func.count()).where(*base_where).group_by(Mistake.status)
    ).all()
    counts = {status: int(count) for status, count in status_rows}
    by_status = [
        StatusCountOut(status=status, count=counts.get(status, 0))
        for status in MISTAKE_STATUSES
    ]

    cause_rows = session.execute(
        select(MistakeAnalysis.cause_type, func.count())
        .join(Mistake, Mistake.id == MistakeAnalysis.mistake_id)
        .where(*base_where)
        .group_by(MistakeAnalysis.cause_type)
        # 并列计数时 DB 不保证行序，显式按 (count DESC, cause_type) 定死，图例不抖。
        .order_by(func.count().desc(), MistakeAnalysis.cause_type)
    ).all()
    by_cause = [CauseCountOut(cause_type=cause, count=int(count)) for cause, count in cause_rows]

    kp_rows = session.execute(
        select(QuestionKp.kp_id, KnowledgePoint.name, func.count())
        .join(Mistake, Mistake.question_id == QuestionKp.question_id)
        .join(KnowledgePoint, KnowledgePoint.id == QuestionKp.kp_id)
        .where(*base_where)
        .group_by(QuestionKp.kp_id, KnowledgePoint.name)
        .order_by(func.count().desc(), QuestionKp.kp_id)
        .limit(10)
    ).all()
    top_kps = [
        KpCountOut(kp_id=kp_id, kp_name=name, count=int(count)) for kp_id, name, count in kp_rows
    ]

    return MistakeStatsOut(
        total=sum(item.count for item in by_status),
        by_status=by_status,
        by_cause=by_cause,
        top_kps=top_kps,
    )


def build_mistakes_query(*, user_id: int, filters: MistakeFilters) -> Select:
    """错题列表查询。

    cause_type / kp_id 都用 EXISTS：JOIN 会在一条错题命中多个知识点时
    产生重复行，分页与 count 一起失真（与 S4-1 build_questions_query 同因）。
    kp_id 命中「题目挂载的知识点」或「诊断结论里的知识点」任一即可。
    """
    stmt = (
        select(Mistake, Question)
        .join(Question, Question.id == Mistake.question_id)
        .where(Mistake.user_id == user_id)
    )
    if filters.status:
        stmt = stmt.where(Mistake.status == filters.status)
    if filters.cause_type:
        stmt = stmt.where(
            exists().where(
                MistakeAnalysis.mistake_id == Mistake.id,
                MistakeAnalysis.cause_type == filters.cause_type,
            )
        )
    if filters.kp_id is not None:
        stmt = stmt.where(
            exists().where(
                QuestionKp.question_id == Mistake.question_id,
                QuestionKp.kp_id == filters.kp_id,
            )
            | exists().where(
                MistakeAnalysis.mistake_id == Mistake.id,
                MistakeAnalysis.kp_ids.contains([filters.kp_id]),
            )
        )
    if filters.created_from is not None:
        stmt = stmt.where(Mistake.created_at >= filters.created_from)
    if filters.created_to is not None:
        stmt = stmt.where(Mistake.created_at <= filters.created_to)
    return stmt


def list_mistakes(
    session: Session,
    *,
    user_id: int,
    filters: MistakeFilters,
    page: PageParams,
    sort: SortParams,
) -> PageData[MistakeSummaryOut]:
    stmt = apply_sort(
        build_mistakes_query(user_id=user_id, filters=filters),
        sort_by=sort.sort_by,
        order=sort.order,
        allowed=SORTABLE,
        default_sort="created_at",
    )
    # 同一秒录入的错题没有唯一 tiebreaker 时翻页会重复/漏行（S4-1 踩过）。
    stmt = stmt.order_by(Mistake.id.desc())
    result = paginate_sa(session, stmt, params=Params(page=page.page, size=page.page_size))
    rows = list(result.items)
    if not rows:
        # 空页没有 id 可批查，直接返回，省掉两条 IN 查询。
        return PageData(items=[], total=result.total, page=result.page, page_size=result.size)

    mistake_ids = [mistake.id for mistake, _ in rows]
    question_ids = [question.id for _, question in rows]
    # 一页各一条 IN 批查，替代逐行 _kp_names/_analysis_of 的 2N 条 SQL（d-8）。
    kp_rows = session.execute(
        select(QuestionKp.question_id, KnowledgePoint.name)
        .join(KnowledgePoint, KnowledgePoint.id == QuestionKp.kp_id)
        .where(QuestionKp.question_id.in_(question_ids))
        # 人工挂载的权重可能全相等（MANUAL_WEIGHT），同权时 DB 不保证行序，
        # 再加 kp_id 让同一题内的 kp_names 顺序完全确定。
        .order_by(QuestionKp.question_id, QuestionKp.weight.desc(), QuestionKp.kp_id)
    ).all()
    kp_names: dict[int, list[str]] = {}
    for question_id, name in kp_rows:
        kp_names.setdefault(question_id, []).append(name)

    # 列表只用 cause_type，不必把 explanation_md 等大字段拉进内存。
    cause_rows = session.execute(
        select(MistakeAnalysis.mistake_id, MistakeAnalysis.cause_type).where(
            MistakeAnalysis.mistake_id.in_(mistake_ids)
        )
    ).all()
    cause_types = {mistake_id: cause_type for mistake_id, cause_type in cause_rows}

    items: list[MistakeSummaryOut] = []
    for mistake, question in rows:
        items.append(
            MistakeSummaryOut(
                id=mistake.id,
                question_id=mistake.question_id,
                status=mistake.status,
                correct_streak=mistake.correct_streak,
                stem_excerpt=question.stem_md[:EXCERPT_LEN],
                subject_id=question.subject_id,
                qtype=question.qtype,
                difficulty=question.difficulty,
                kp_names=kp_names.get(question.id, []),
                cause_type=cause_types.get(mistake.id),
                has_image=mistake.image_file_id is not None,
                created_at=mistake.created_at,
                last_review_at=mistake.last_review_at,
            )
        )
    return PageData(items=items, total=result.total, page=result.page, page_size=result.size)
