"""S5-6 学习报告：窗口聚合、模块雷达、热力节点、趋势与周报统计。

纯函数与 DB 用例分开；本模块不 commit，由路由/调用方提交。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, func, literal_column, select
from sqlalchemy.orm import Session

from app.models.enums import MistakeStatus
from app.models.knowledge_point import KnowledgePoint
from app.models.mastery import Mastery
from app.models.mistake import Mistake
from app.models.note import Note
from app.models.review_item import ReviewItem
from app.models.subject import Subject
from app.schemas.report import (
    ReportHeatmapNodeOut,
    ReportModuleOut,
    ReportOverviewOut,
    ReportRangeOut,
    ReportSubjectOut,
    ReportTrendPointOut,
)
from app.services import mastery_service, stats_service

RANGES: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}
DEFAULT_RANGE = "30d"

Window = stats_service.Window


def build_window(range_key: str, *, now: datetime | None = None) -> Window:
    return stats_service.build_window(range_key, now=now)


def fill_days(rows: Mapping[date, int], dates: Sequence[date]) -> list[tuple[date, int]]:
    return stats_service.fill_days(rows, dates)


def build_trend(
    dates: Sequence[date],
    *,
    new_notes: Mapping[date, int],
    reviews_done: Mapping[date, int],
    new_mistakes: Mapping[date, int],
    mastered_mistakes: Mapping[date, int],
) -> list[ReportTrendPointOut]:
    points: list[ReportTrendPointOut] = []
    for day in dates:
        new_note_count = int(new_notes.get(day, 0))
        review_count = int(reviews_done.get(day, 0))
        new_mistake_count = int(new_mistakes.get(day, 0))
        mastered_count = int(mastered_mistakes.get(day, 0))
        points.append(
            ReportTrendPointOut(
                date=day,
                new_notes=new_note_count,
                reviews_done=review_count,
                new_mistakes=new_mistake_count,
                mastered_mistakes=mastered_count,
                mistakes_net=new_mistake_count - mastered_count,
            )
        )
    return points

@dataclass(frozen=True, slots=True)
class KpNode:
    kp_id: int
    subject_id: int
    parent_id: int | None
    name: str
    level: int
    exam_weight: float | None = None


def _utc_day(column: Any) -> Any:
    return func.date_trunc(literal_column("'day'"), column).cast(Date)


def _module_of(node: KpNode, by_id: dict[int, KpNode]) -> int | None:
    current: KpNode | None = node
    while current is not None and current.level > 2:
        current = by_id.get(current.parent_id) if current.parent_id else None
    return current.kp_id if current is not None and current.level == 2 else None


def build_subjects(
    nodes: Sequence[KpNode],
    subjects: Sequence[tuple[int, str]],
    *,
    mastery_raw: Mapping[int, float],
    mastery_t: Mapping[int, float],
) -> list[ReportSubjectOut]:
    by_id = {node.kp_id: node for node in nodes}
    module_counts: dict[int, list[int]] = {}
    module_sums: dict[int, float] = {}
    heatmap_by_subject: dict[int, list[ReportHeatmapNodeOut]] = {}

    for node in nodes:
        module_id = _module_of(node, by_id)
        if module_id is None:
            continue
        counts = module_counts.setdefault(module_id, [0, 0])
        counts[0] += 1
        if node.kp_id in mastery_t:
            counts[1] += 1
            module_sums[module_id] = (
                module_sums.get(module_id, 0.0) + mastery_t[node.kp_id]
            )
        heatmap_by_subject.setdefault(node.subject_id, []).append(
            ReportHeatmapNodeOut(
                kp_id=node.kp_id,
                kp_name=node.name,
                parent_id=None if node.level == 2 else node.parent_id,
                level=node.level,
                exam_weight=node.exam_weight,
                mastery=mastery_raw.get(node.kp_id),
                mastery_t=mastery_t.get(node.kp_id),
                color_value=(
                    round(1.0 - mastery_t[node.kp_id], 3)
                    if node.kp_id in mastery_t
                    else None
                ),
                assessed=node.kp_id in mastery_t,
            )
        )

    modules_by_subject: dict[int, list[ReportModuleOut]] = {}
    for node in nodes:
        if node.level != 2:
            continue
        total, assessed = module_counts.get(node.kp_id, [0, 0])
        modules_by_subject.setdefault(node.subject_id, []).append(
            ReportModuleOut(
                kp_id=node.kp_id,
                kp_name=node.name,
                exam_weight=node.exam_weight,
                kp_count=total,
                assessed_count=assessed,
                mastery=(
                    round(module_sums[node.kp_id] / assessed, 3)
                    if assessed
                    else None
                ),
            )
        )

    result: list[ReportSubjectOut] = []
    for subject_id, subject_name in sorted(subjects):
        modules = sorted(
            modules_by_subject.get(subject_id, []), key=lambda item: item.kp_id
        )
        heatmap = sorted(
            heatmap_by_subject.get(subject_id, []),
            key=lambda item: (item.level, item.kp_id),
        )
        if modules:
            result.append(
                ReportSubjectOut(
                    subject_id=subject_id,
                    subject_name=subject_name,
                    modules=modules,
                    heatmap=heatmap,
                )
            )
    return result


def _load_nodes(session: Session) -> list[KpNode]:
    rows = session.execute(
        select(
            KnowledgePoint.id,
            KnowledgePoint.subject_id,
            KnowledgePoint.parent_id,
            KnowledgePoint.name,
            KnowledgePoint.level,
            KnowledgePoint.exam_weight,
        )
        .where(KnowledgePoint.level >= 2, KnowledgePoint.level <= 4)
        .order_by(KnowledgePoint.level.asc(), KnowledgePoint.id.asc())
    ).all()
    return [
        KpNode(
            kp_id=int(kp_id),
            subject_id=int(subject_id),
            parent_id=int(parent_id) if parent_id is not None else None,
            name=name,
            level=int(level),
            exam_weight=float(weight) if weight is not None else None,
        )
        for kp_id, subject_id, parent_id, name, level, weight in rows
    ]


def _load_mastery(session: Session, *, user_id: int) -> list[tuple]:
    return session.execute(
        select(
            Mastery.kp_id,
            Mastery.mastery,
            Mastery.stability,
            Mastery.last_practice_at,
        ).where(Mastery.user_id == user_id)
    ).all()


def _mastery_maps(
    rows: Sequence[tuple], *, now: datetime
) -> tuple[dict[int, float], dict[int, float]]:
    raw: dict[int, float] = {}
    effective: dict[int, float] = {}
    for kp_id, mastery, stability, last_practice_at in rows:
        days = 0.0
        if last_practice_at is not None:
            days = max(0.0, (now - last_practice_at).total_seconds() / 86400.0)
        raw[int(kp_id)] = float(mastery)
        effective[int(kp_id)] = mastery_service.decayed_mastery(
            float(mastery), float(stability), days=days
        )
    return raw, effective


def _daily(session: Session, statement: Any) -> dict[date, int]:
    return {day: int(count) for day, count in session.execute(statement).all()}


def _load_trend(
    session: Session, *, user_id: int, window: Window
) -> list[ReportTrendPointOut]:
    notes = _daily(
        session,
        select(_utc_day(Note.created_at), func.count())
        .where(
            Note.user_id == user_id,
            Note.deleted_at.is_(None),
            Note.created_at >= window.start,
            Note.created_at <= window.end,
        )
        .group_by(_utc_day(Note.created_at)),
    )
    reviews = _daily(
        session,
        select(_utc_day(ReviewItem.done_at), func.count())
        .where(
            ReviewItem.user_id == user_id,
            ReviewItem.done_at.is_not(None),
            ReviewItem.done_at >= window.start,
            ReviewItem.done_at <= window.end,
        )
        .group_by(_utc_day(ReviewItem.done_at)),
    )
    mistakes = _daily(
        session,
        select(_utc_day(Mistake.created_at), func.count())
        .where(
            Mistake.user_id == user_id,
            Mistake.created_at >= window.start,
            Mistake.created_at <= window.end,
        )
        .group_by(_utc_day(Mistake.created_at)),
    )
    mastered = _daily(
        session,
        select(_utc_day(Mistake.last_review_at), func.count())
        .where(
            Mistake.user_id == user_id,
            Mistake.status == MistakeStatus.MASTERED.value,
            Mistake.last_review_at.is_not(None),
            Mistake.last_review_at >= window.start,
            Mistake.last_review_at <= window.end,
        )
        .group_by(_utc_day(Mistake.last_review_at)),
    )
    return build_trend(
        window.dates,
        new_notes=notes,
        reviews_done=reviews,
        new_mistakes=mistakes,
        mastered_mistakes=mastered,
    )


def get_overview(
    session: Session,
    *,
    user_id: int,
    range_key: str = DEFAULT_RANGE,
    now: datetime | None = None,
) -> ReportOverviewOut:
    window = build_window(range_key, now=now)
    moment = window.end
    nodes = _load_nodes(session)
    subject_ids = sorted({node.subject_id for node in nodes})
    subject_rows = (
        session.execute(
            select(Subject.id, Subject.name)
            .where(Subject.id.in_(subject_ids))
            .order_by(Subject.id.asc())
        ).all()
        if subject_ids
        else []
    )
    raw, effective = _mastery_maps(_load_mastery(session, user_id=user_id), now=moment)
    return ReportOverviewOut(
        range=ReportRangeOut(
            key=window.key, from_=window.dates[0], to=window.dates[-1]
        ),
        subjects=build_subjects(
            nodes,
            [(int(sid), name) for sid, name in subject_rows],
            mastery_raw=raw,
            mastery_t=effective,
        ),
        trend=_load_trend(session, user_id=user_id, window=window),
    )
