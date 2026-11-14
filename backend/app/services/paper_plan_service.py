"""S5-2 组卷服务：取候选、生成预览、换题、保存、读取（算法全部复用 paper_service）。"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, InvalidParamError, NotFoundError
from app.models.mistake import Mistake
from app.models.paper import Paper
from app.models.question import Question
from app.models.question_kp import QuestionKp
from app.schemas.common import PageData
from app.schemas.paper import (
    OptionOut,
    PaperConstraintIn,
    PaperConstraintOut,
    PaperDetailOut,
    PaperGenerateIn,
    PaperItemOut,
    PaperOut,
    PaperPreviewOut,
    PaperReplaceIn,
    PaperReplaceOut,
    PaperSaveIn,
    PaperSummaryOut,
    PaperViolationOut,
    ScorePartsOut,
)
from app.services import mastery_service, paper_service
from app.services.paper_service import CandidateQuestion, PaperConstraints, PaperItem
from app.utils.pagination import PageParams, paginate_query

SEED_MAX = 2**31 - 1


@dataclass(frozen=True, slots=True)
class CandidateData:
    candidates: tuple[CandidateQuestion, ...]
    mastery_by_kp: dict[int, float]


def build_constraints(payload: PaperConstraintIn) -> PaperConstraints:
    """把 DTO 归一化成内核约束；内核拒绝的入参统一翻成 422。"""
    qtype_ratio = {
        qtype: float(weight) for qtype, weight in payload.qtype_ratio.items() if weight > 0
    }
    if not qtype_ratio:
        raise InvalidParamError("请至少给一个题型设置占比")
    seed = payload.seed if payload.seed is not None else secrets.randbelow(SEED_MAX + 1)
    try:
        return PaperConstraints(
            kp_ids=tuple(payload.kp_ids),
            total_questions=payload.total_questions,
            qtype_ratio=qtype_ratio,
            difficulty_dist={
                int(key): float(value) for key, value in payload.difficulty_dist.items()
            },
            total_score_target=payload.total_score,
            kp_weights=(
                {int(key): float(value) for key, value in payload.kp_weights.items()}
                if payload.kp_weights
                else None
            ),
            exclude_recent_days=payload.exclude_recent_days,
            duration_min=payload.duration_min,
            seed=seed,
        )
    except paper_service.PaperPlanError as exc:
        raise InvalidParamError(str(exc)) from exc


def normalized_constraint(constraints: PaperConstraints) -> PaperConstraintOut:
    """权重归一化后回显；分值表一并回显，前端据此解释总分。"""

    def normalize(weights: Mapping[object, float]) -> dict[object, float]:
        total = sum(float(value) for value in weights.values())
        return {key: round(float(value) / total, 6) for key, value in weights.items()}

    return PaperConstraintOut(
        kp_ids=list(constraints.kp_ids),
        total_questions=constraints.total_questions,
        qtype_ratio={
            str(key): value for key, value in normalize(constraints.qtype_ratio).items()
        },
        difficulty_dist={
            int(key): value for key, value in normalize(constraints.difficulty_dist).items()
        },
        total_score=constraints.total_score_target,
        duration_min=constraints.duration_min,
        exclude_recent_days=constraints.exclude_recent_days,
        seed=constraints.seed,
        kp_weights=constraints.kp_weight_map,
        score_by_qtype=constraints.score_map,
    )


def load_candidates(
    session: Session,
    constraints: PaperConstraints,
    *,
    user_id: int,
    now: datetime,
) -> CandidateData:
    """三条批量查询：题目↔知识点、本人最近做过的题、本人掌握度。"""
    kp_ids = list(constraints.kp_ids)
    rows = session.execute(
        select(
            Question.id,
            Question.qtype,
            Question.difficulty,
            Question.verified,
            Question.origin,
            QuestionKp.kp_id,
            QuestionKp.weight,
        )
        .join(QuestionKp, QuestionKp.question_id == Question.id)
        .where(QuestionKp.kp_id.in_(kp_ids))
    ).all()
    grouped: dict[int, dict[str, object]] = {}
    for question_id, qtype, difficulty, verified, origin, kp_id, weight in rows:
        entry = grouped.setdefault(
            int(question_id),
            {
                "qtype": str(qtype),
                "difficulty": int(difficulty),
                "verified": bool(verified),
                "origin": str(origin),
                "kps": [],
            },
        )
        entry["kps"].append(
            (int(kp_id), float(weight) if weight is not None else 1.0)
        )
    last_done = _last_done_at(session, user_id=user_id, question_ids=list(grouped))
    candidates = tuple(
        CandidateQuestion(
            question_id=question_id,
            qtype=str(grouped[question_id]["qtype"]),
            difficulty=int(grouped[question_id]["difficulty"]),
            kp_weights=tuple(grouped[question_id]["kps"]),
            verified=bool(grouped[question_id]["verified"]),
            origin=str(grouped[question_id]["origin"]),
            last_done_at=last_done.get(question_id),
        )
        for question_id in sorted(grouped)
    )
    mastery_by_kp = mastery_service.mastery_values(
        session, user_id=user_id, kp_ids=constraints.kp_ids, now=now
    )
    return CandidateData(candidates=candidates, mastery_by_kp=mastery_by_kp)


def _last_done_at(
    session: Session, *, user_id: int, question_ids: Sequence[int]
) -> dict[int, datetime]:
    """本人每道题最近一次「做过」的时间 = max(last_review_at, created_at)。"""
    if not question_ids:
        return {}
    rows = session.execute(
        select(Mistake.question_id, Mistake.last_review_at, Mistake.created_at).where(
            Mistake.user_id == user_id, Mistake.question_id.in_(list(question_ids))
        )
    ).all()
    result: dict[int, datetime] = {}
    for question_id, last_review_at, created_at in rows:
        moments = [moment for moment in (last_review_at, created_at) if moment is not None]
        if not moments:
            continue
        moment = max(moments)
        current = result.get(int(question_id))
        if current is None or moment > current:
            result[int(question_id)] = moment
    return result

@dataclass(frozen=True, slots=True)
class QuestionDetail:
    question_id: int
    subject_id: int
    qtype: str
    difficulty: int
    stem_md: str
    options: tuple[dict[str, str], ...]
    answer_md: str | None
    analysis_md: str | None
    verified: bool
    origin: str


def load_question_details(
    session: Session, question_ids: Sequence[int]
) -> dict[int, QuestionDetail]:
    unique = list(dict.fromkeys(int(question_id) for question_id in question_ids))
    if not unique:
        return {}
    rows = session.execute(
        select(
            Question.id,
            Question.subject_id,
            Question.qtype,
            Question.difficulty,
            Question.stem_md,
            Question.options_json,
            Question.answer_md,
            Question.analysis_md,
            Question.verified,
            Question.origin,
        ).where(Question.id.in_(unique))
    ).all()
    details: dict[int, QuestionDetail] = {}
    for (
        question_id,
        subject_id,
        qtype,
        difficulty,
        stem_md,
        options_json,
        answer_md,
        analysis_md,
        verified,
        origin,
    ) in rows:
        options = tuple(
            {"key": str(item.get("key", "")), "text": str(item.get("text", ""))}
            for item in (options_json or [])
        )
        details[int(question_id)] = QuestionDetail(
            question_id=int(question_id),
            subject_id=int(subject_id),
            qtype=str(qtype),
            difficulty=int(difficulty),
            stem_md=str(stem_md),
            options=options,
            answer_md=answer_md,
            analysis_md=analysis_md,
            verified=bool(verified),
            origin=str(origin),
        )
    return details


def kp_ids_by_question(session: Session, question_ids: Sequence[int]) -> dict[int, list[int]]:
    unique = list(dict.fromkeys(int(question_id) for question_id in question_ids))
    if not unique:
        return {}
    rows = session.execute(
        select(QuestionKp.question_id, QuestionKp.kp_id)
        .where(QuestionKp.question_id.in_(unique))
        .order_by(QuestionKp.question_id, QuestionKp.kp_id)
    ).all()
    result: dict[int, list[int]] = {}
    for question_id, kp_id in rows:
        result.setdefault(int(question_id), []).append(int(kp_id))
    return result


def _item_out(
    item: PaperItem,
    detail: QuestionDetail,
    *,
    score: int | None = None,
    parts: ScorePartsOut | None = None,
) -> PaperItemOut:
    return PaperItemOut(
        question_id=item.question_id,
        qtype=item.qtype,
        difficulty=item.difficulty,
        score=item.score if score is None else score,
        kp_ids=list(item.kp_ids),
        parts=parts
        or ScorePartsOut(
            difficulty_match=item.parts.difficulty_match,
            mastery_match=item.parts.mastery_match,
            novelty=item.parts.novelty,
            quality=item.parts.quality,
            total=item.parts.total,
        ),
        subject_id=detail.subject_id,
        stem_md=detail.stem_md,
        options=[OptionOut(**option) for option in detail.options],
        answer_md=detail.answer_md,
        analysis_md=detail.analysis_md,
        verified=detail.verified,
        origin=detail.origin,
    )


def generate_preview(
    session: Session,
    payload: PaperGenerateIn,
    *,
    user_id: int,
    now: datetime,
) -> PaperPreviewOut:
    constraints = build_constraints(payload)
    data = load_candidates(session, constraints, user_id=user_id, now=now)
    try:
        plan = paper_service.plan_paper(
            constraints,
            data.candidates,
            mastery_by_kp=data.mastery_by_kp,
            now=now,
        )
    except paper_service.PaperPlanError as exc:
        raise InvalidParamError(str(exc)) from exc
    details = load_question_details(session, [item.question_id for item in plan.items])
    missing = [item.question_id for item in plan.items if item.question_id not in details]
    if missing:
        raise InvalidParamError("有候选题已被删除，请重新生成试卷")
    return PaperPreviewOut(
        constraint=normalized_constraint(constraints),
        seed=plan.seed,
        ok=plan.ok,
        items=[_item_out(item, details[item.question_id]) for item in plan.items],
        total_score=plan.total_score,
        target_score=plan.target_score,
        quota_by_qtype=plan.quota_by_qtype,
        quota_by_difficulty=plan.quota_by_difficulty,
        quota_by_kp=plan.quota_by_kp,
        counts_by_qtype=plan.counts_by_qtype,
        counts_by_difficulty=plan.counts_by_difficulty,
        counts_by_kp=plan.counts_by_kp,
        violations=[
            PaperViolationOut(code=violation.code, message=violation.message, detail=violation.detail)
            for violation in plan.violations
        ],
        warnings=list(plan.warnings),
    )


def replace_item(
    session: Session,
    payload: PaperReplaceIn,
    *,
    user_id: int,
    now: datetime,
) -> PaperReplaceOut:
    constraints = build_constraints(payload)
    data = load_candidates(session, constraints, user_id=user_id, now=now)
    original = next(
        (
            candidate
            for candidate in data.candidates
            if candidate.question_id == payload.replace_question_id
        ),
        None,
    )
    if original is None:
        return PaperReplaceOut(
            replaced=False, item=None, reason="原题不在候选池中，无法判断题型与难度"
        )
    pool, _excluded_recent = paper_service.prepare_pool(
        constraints, data.candidates, now=now
    )
    excluded = set(payload.selected_question_ids) | {payload.replace_question_id}
    available = [candidate for candidate in pool if candidate.question_id not in excluded]
    scored = [
        (
            paper_service.score_parts(
                candidate=candidate,
                constraints=constraints,
                mastery_by_kp=data.mastery_by_kp,
                now=now,
            ),
            candidate,
        )
        for candidate in available
    ]
    scored.sort(key=lambda pair: (-pair[0].total, pair[1].question_id))

    chosen = next(
        (
            (parts, candidate)
            for parts, candidate in scored
            if candidate.qtype == original.qtype
            and candidate.difficulty == original.difficulty
        ),
        None,
    )
    if chosen is None:
        chosen = next(
            (
                (parts, candidate)
                for parts, candidate in scored
                if candidate.qtype == original.qtype
            ),
            None,
        )
    if chosen is None:
        return PaperReplaceOut(
            replaced=False, item=None, reason="没有可替换的候选题"
        )
    parts, candidate = chosen
    details = load_question_details(session, [candidate.question_id])
    detail = details.get(candidate.question_id)
    if detail is None:
        return PaperReplaceOut(
            replaced=False, item=None, reason="候选题已被删除，请重试"
        )
    item = PaperItem(
        question_id=candidate.question_id,
        qtype=candidate.qtype,
        difficulty=candidate.difficulty,
        score=int(constraints.score_map[candidate.qtype]),
        kp_ids=tuple(kp_id for kp_id, _weight in candidate.kp_weights),
        parts=parts,
    )
    return PaperReplaceOut(replaced=True, item=_item_out(item, detail), reason=None)


def save_draft(session: Session, payload: PaperSaveIn, *, user_id: int) -> PaperOut:
    """保存草稿：总分按题目分值表重算（不信任前端），一次事务提交。"""
    question_ids = list(payload.question_ids)
    rows = session.execute(
        select(Question.id, Question.qtype).where(Question.id.in_(question_ids))
    ).all()
    qtype_by_id = {int(question_id): str(qtype) for question_id, qtype in rows}
    missing = [question_id for question_id in question_ids if question_id not in qtype_by_id]
    if missing:
        raise InvalidParamError("有题目已不存在，请重新选择")
    score_map = paper_service.DEFAULT_SCORE_BY_QTYPE
    total_score = sum(int(score_map[qtype_by_id[question_id]]) for question_id in question_ids)
    constraints = build_constraints(payload.constraint)
    paper = Paper(
        user_id=user_id,
        title=payload.title,
        constraint_json=normalized_constraint(constraints).model_dump(mode="json"),
        question_ids=question_ids,
        total_score=total_score,
        duration_min=payload.duration_min,
        status="草稿",
        generated_by="manual",
    )
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return PaperOut.model_validate(paper)


def list_papers(
    session: Session, *, user_id: int, params: PageParams
) -> PageData[PaperSummaryOut]:
    """只列本人试卷；固定保存时间倒序，同一秒内用 id 兜底稳定顺序。"""
    stmt = (
        select(Paper)
        .where(Paper.user_id == user_id)
        .order_by(Paper.created_at.desc(), Paper.id.desc())
    )
    return paginate_query(session, stmt, params, item_model=PaperSummaryOut)


def get_paper(session: Session, *, user_id: int, paper_id: int) -> PaperDetailOut:
    """读本人试卷：顺序按存库数组；题目被硬删则跳过并如实回报。"""
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise NotFoundError("试卷不存在")
    if paper.user_id != user_id:
        raise ForbiddenError("无权访问该试卷")
    question_ids = [int(question_id) for question_id in paper.question_ids]
    details = load_question_details(session, question_ids)
    kp_map = kp_ids_by_question(
        session, [question_id for question_id in question_ids if question_id in details]
    )
    score_map = paper_service.DEFAULT_SCORE_BY_QTYPE
    items: list[PaperItemOut] = []
    for question_id in question_ids:
        detail = details.get(question_id)
        if detail is None:
            continue
        items.append(
            PaperItemOut(
                question_id=detail.question_id,
                qtype=detail.qtype,
                difficulty=detail.difficulty,
                score=int(score_map[detail.qtype]),
                kp_ids=kp_map.get(detail.question_id, []),
                parts=None,
                subject_id=detail.subject_id,
                stem_md=detail.stem_md,
                options=[OptionOut(**option) for option in detail.options],
                answer_md=detail.answer_md,
                analysis_md=detail.analysis_md,
                verified=detail.verified,
                origin=detail.origin,
            )
        )
    return PaperDetailOut(
        id=paper.id,
        title=paper.title,
        status=paper.status,
        total_score=paper.total_score,
        duration_min=paper.duration_min,
        question_ids=question_ids,
        created_at=paper.created_at,
        constraint_json=paper.constraint_json,
        items=items,
        missing_question_ids=[
            question_id for question_id in question_ids if question_id not in details
        ],
    )
