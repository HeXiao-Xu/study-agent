"""S5-2 组卷服务：取候选、生成预览、换题、保存、读取（算法全部复用 paper_service）。"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidParamError
from app.models.mistake import Mistake
from app.models.question import Question
from app.models.question_kp import QuestionKp
from app.schemas.paper import (
    OptionOut,
    PaperConstraintIn,
    PaperConstraintOut,
    PaperGenerateIn,
    PaperItemOut,
    PaperPreviewOut,
    PaperReplaceIn,
    PaperReplaceOut,
    PaperViolationOut,
    ScorePartsOut,
)
from app.services import mastery_service, paper_service
from app.services.paper_service import CandidateQuestion, PaperConstraints, PaperItem

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
        raise InvalidParamError("qtype_ratio 至少一个题型配比大于 0")
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
        raise InvalidParamError(f"候选题已被删除，请重试：{missing[:10]}")
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
