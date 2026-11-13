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
    PaperItemOut,
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