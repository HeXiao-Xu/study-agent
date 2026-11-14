"""S5-5 复习调度（spec §4）。

前半部分是纯函数，便于手推与单测；DB 用例在后续任务补。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError, InvalidParamError, NotFoundError
from app.models.enums import ReviewRefType
from app.models.knowledge_point import KnowledgePoint
from app.models.mastery import Mastery
from app.models.mistake import Mistake
from app.models.question import Question
from app.models.question_kp import QuestionKp
from app.models.review_item import ReviewItem
from app.schemas.review import ReviewItemOut, ReviewTodayOut
from app.services.mastery_service import decayed_mastery, review_interval_days

LOW_MASTERY = 0.4
DEFAULT_CAP_MINUTES = 35
ESTIMATE_BASE_MINUTES: dict[str, int] = {
    ReviewRefType.NOTE.value: 3,
    ReviewRefType.QUESTION.value: 3,
    ReviewRefType.MISTAKE.value: 4,
}
ACTION_DONE = "done"
ACTION_SKIP = "skip"
ACTION_LATER = "later"


@dataclass(frozen=True, slots=True)
class MasterySnapshot:
    kp_id: int
    kp_name: str
    subject_id: int
    exam_weight: float | None
    mastery: float
    stability: float
    attempts: int
    last_practice_at: datetime | None
    due_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RefChoice:
    ref_type: str
    ref_id: int
    difficulty: int


@dataclass(frozen=True, slots=True)
class ItemPlan:
    kp_id: int
    kp_name: str
    subject_id: int
    ref_type: str
    ref_id: int
    due_at: datetime
    interval_days: int
    priority: float
    estimated_minutes: int
    mastery: float
    mastery_t: float
    stability: float
    attempts: int
    overdue_days: float
    low_mastery: bool


@dataclass(frozen=True, slots=True)
class RefDetail:
    title: str | None
    available: bool
    difficulty: int


@dataclass(frozen=True, slots=True)
class ReviewRowSnapshot:
    item: object
    kp_name: str
    subject_id: int
    exam_weight: float | None
    mastery: float
    stability: float
    attempts: int
    last_practice_at: datetime | None


def _timezone() -> ZoneInfo:
    return ZoneInfo(get_settings().review_timezone)


def local_bounds(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime, date]:
    local = now.astimezone(tz)
    start = datetime.combine(local.date(), time.min, tzinfo=tz)
    next_start = start + timedelta(days=1)
    return start.astimezone(timezone.utc), next_start.astimezone(timezone.utc), local.date()


def overdue_days(due_at: datetime, now: datetime) -> float:
    return round(max(0.0, (now - due_at).total_seconds() / 86400.0), 2)


def overdue_ratio(due_at: datetime, now: datetime, interval_days: int) -> float:
    days = max(0.0, (now - due_at).total_seconds() / 86400.0)
    return round(min(1.0, days / max(1, interval_days)), 4)


def review_priority(mastery_t: float, overdue: float, exam_weight: float | None) -> float:
    weight = 0.5 if exam_weight is None else float(exam_weight)
    raw = 0.5 * (1.0 - mastery_t) + 0.3 * overdue + 0.2 * weight
    return round(min(1.0, max(0.0, raw)), 4)


def estimated_minutes(ref_type: str, difficulty: int) -> int:
    safe_difficulty = min(5, max(1, int(difficulty)))
    return ESTIMATE_BASE_MINUTES.get(ref_type, 3) + safe_difficulty


def is_candidate(mastery_t: float, due_at: datetime, *, next_start: datetime) -> bool:
    return mastery_t < LOW_MASTERY or due_at < next_start


def _sort_key(plan: ItemPlan) -> tuple[float, float, int]:
    return (-plan.priority, plan.mastery_t, plan.kp_id)


def select_capped(
    plans: Sequence[ItemPlan], cap_minutes: int
) -> tuple[list[ItemPlan], list[ItemPlan]]:
    selected: list[ItemPlan] = []
    deferred: list[ItemPlan] = []
    total = 0
    for plan in sorted(plans, key=_sort_key):
        if not selected or total + plan.estimated_minutes <= cap_minutes:
            selected.append(plan)
            total += plan.estimated_minutes
        else:
            deferred.append(plan)
    return selected, deferred

def _load_mastery_snapshots(session: Session, user_id: int) -> list[MasterySnapshot]:
    rows = session.execute(
        select(
            Mastery,
            KnowledgePoint.name,
            KnowledgePoint.subject_id,
            KnowledgePoint.exam_weight,
        )
        .join(KnowledgePoint, KnowledgePoint.id == Mastery.kp_id)
        .where(Mastery.user_id == user_id)
    ).all()
    return [
        MasterySnapshot(
            kp_id=mastery.kp_id,
            kp_name=name,
            subject_id=subject_id,
            exam_weight=float(exam_weight) if exam_weight is not None else None,
            mastery=float(mastery.mastery),
            stability=float(mastery.stability),
            attempts=mastery.attempts,
            last_practice_at=mastery.last_practice_at,
            due_at=mastery.due_at,
        )
        for mastery, name, subject_id, exam_weight in rows
    ]


def _summary(text_md: str | None) -> str | None:
    if not text_md:
        return None
    collapsed = " ".join(text_md.split())
    return collapsed[:120] or None


def _load_ref_choices(
    session: Session, *, user_id: int, kp_ids: Sequence[int]
) -> dict[int, RefChoice]:
    unique_kp_ids = sorted({int(kp_id) for kp_id in kp_ids})
    if not unique_kp_ids:
        return {}
    chosen: dict[int, RefChoice] = {}

    mistake_rows = session.execute(
        select(Mistake.id, QuestionKp.kp_id, Question.difficulty)
        .join(Question, Question.id == Mistake.question_id)
        .join(QuestionKp, QuestionKp.question_id == Mistake.question_id)
        .where(
            Mistake.user_id == user_id,
            Mistake.status.in_(["待订正", "已订正"]),
            QuestionKp.kp_id.in_(unique_kp_ids),
        )
        .order_by(
            case((Mistake.status == "待订正", 0), else_=1),
            func.coalesce(Mistake.last_review_at, Mistake.created_at).desc(),
            Mistake.id.desc(),
        )
    ).all()
    for mistake_id, kp_id, difficulty in mistake_rows:
        chosen.setdefault(
            kp_id,
            RefChoice(ReviewRefType.MISTAKE.value, int(mistake_id), int(difficulty or 3)),
        )

    missing = [kp_id for kp_id in unique_kp_ids if kp_id not in chosen]
    if missing:
        question_rows = session.execute(
            select(QuestionKp.kp_id, Question.id, Question.difficulty)
            .join(Question, Question.id == QuestionKp.question_id)
            .where(QuestionKp.kp_id.in_(missing))
            .order_by(
                QuestionKp.kp_id.asc(),
                QuestionKp.weight.desc().nulls_last(),
                Question.difficulty.asc(),
                Question.id.asc(),
            )
        ).all()
        for kp_id, question_id, difficulty in question_rows:
            chosen.setdefault(
                kp_id,
                RefChoice(
                    ReviewRefType.QUESTION.value,
                    int(question_id),
                    int(difficulty or 3),
                ),
            )
    return chosen


def _load_items(session: Session, user_id: int) -> dict[int, ReviewItem]:
    return {
        row.kp_id: row
        for row in session.scalars(select(ReviewItem).where(ReviewItem.user_id == user_id))
    }


def _upsert_item(
    session: Session,
    *,
    user_id: int,
    plan: ItemPlan,
    clear_done: bool,
) -> None:
    values = {
        "user_id": user_id,
        "kp_id": plan.kp_id,
        "ref_type": plan.ref_type,
        "ref_id": plan.ref_id,
        "due_at": plan.due_at,
        "interval_days": plan.interval_days,
        "priority": Decimal(str(plan.priority)),
    }
    set_values = {
        "ref_type": plan.ref_type,
        "ref_id": plan.ref_id,
        "due_at": plan.due_at,
        "interval_days": plan.interval_days,
        "priority": Decimal(str(plan.priority)),
    }
    if clear_done:
        values["done_at"] = None
        set_values["done_at"] = None
    stmt = (
        pg_insert(ReviewItem)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["user_id", "kp_id"],
            set_=set_values,
        )
    )
    session.execute(stmt)


def _load_today_snapshots(
    session: Session, *, user_id: int, next_start: datetime
) -> list[ReviewRowSnapshot]:
    rows = session.execute(
        select(
            ReviewItem,
            Mastery,
            KnowledgePoint.name,
            KnowledgePoint.subject_id,
            KnowledgePoint.exam_weight,
        )
        .join(KnowledgePoint, KnowledgePoint.id == ReviewItem.kp_id)
        .outerjoin(
            Mastery,
            and_(
                Mastery.user_id == ReviewItem.user_id,
                Mastery.kp_id == ReviewItem.kp_id,
            ),
        )
        .where(
            ReviewItem.user_id == user_id,
            ReviewItem.done_at.is_(None),
            ReviewItem.due_at < next_start,
        )
    ).all()
    return [
        ReviewRowSnapshot(
            item=item,
            kp_name=name,
            subject_id=subject_id,
            exam_weight=float(exam_weight) if exam_weight is not None else None,
            mastery=float(mastery.mastery) if mastery is not None else 0.0,
            stability=float(mastery.stability) if mastery is not None else 2.0,
            attempts=mastery.attempts if mastery is not None else 0,
            last_practice_at=mastery.last_practice_at if mastery is not None else None,
        )
        for item, mastery, name, subject_id, exam_weight in rows
    ]


def _load_item_snapshot(
    session: Session, *, user_id: int, item_id: int
) -> ReviewRowSnapshot | None:
    row = session.execute(
        select(
            ReviewItem,
            Mastery,
            KnowledgePoint.name,
            KnowledgePoint.subject_id,
            KnowledgePoint.exam_weight,
        )
        .join(KnowledgePoint, KnowledgePoint.id == ReviewItem.kp_id)
        .outerjoin(
            Mastery,
            and_(
                Mastery.user_id == ReviewItem.user_id,
                Mastery.kp_id == ReviewItem.kp_id,
            ),
        )
        .where(ReviewItem.id == item_id, ReviewItem.user_id == user_id)
    ).first()
    if row is None:
        return None
    item, mastery, name, subject_id, exam_weight = row
    return ReviewRowSnapshot(
        item=item,
        kp_name=name,
        subject_id=subject_id,
        exam_weight=float(exam_weight) if exam_weight is not None else None,
        mastery=float(mastery.mastery) if mastery is not None else 0.0,
        stability=float(mastery.stability) if mastery is not None else 2.0,
        attempts=mastery.attempts if mastery is not None else 0,
        last_practice_at=mastery.last_practice_at if mastery is not None else None,
    )


def _ref_details(
    session: Session, *, user_id: int, rows: Sequence[ReviewRowSnapshot]
) -> dict[tuple[str, int], RefDetail]:
    details: dict[tuple[str, int], RefDetail] = {}
    question_ids = [
        row.item.ref_id
        for row in rows
        if row.item.ref_type == ReviewRefType.QUESTION
    ]
    mistake_ids = [
        row.item.ref_id for row in rows if row.item.ref_type == ReviewRefType.MISTAKE
    ]
    if question_ids:
        for question_id, stem_md, difficulty in session.execute(
            select(Question.id, Question.stem_md, Question.difficulty).where(
                Question.id.in_(question_ids)
            )
        ).all():
            details[(ReviewRefType.QUESTION.value, int(question_id))] = RefDetail(
                _summary(stem_md), True, int(difficulty or 3)
            )
    if mistake_ids:
        for mistake_id, stem_md, difficulty in session.execute(
            select(Mistake.id, Question.stem_md, Question.difficulty)
            .join(Question, Question.id == Mistake.question_id)
            .where(Mistake.id.in_(mistake_ids), Mistake.user_id == user_id)
        ).all():
            details[(ReviewRefType.MISTAKE.value, int(mistake_id))] = RefDetail(
                _summary(stem_md), True, int(difficulty or 3)
            )
    for row in rows:
        details.setdefault(
            (row.item.ref_type, row.item.ref_id), RefDetail(None, False, 3)
        )
    return details


def _item_out(
    row: ReviewRowSnapshot, detail: RefDetail, *, now: datetime
) -> ReviewItemOut:
    days = 0.0
    if row.last_practice_at is not None:
        days = max(0.0, (now - row.last_practice_at).total_seconds() / 86400.0)
    mastery_t = decayed_mastery(row.mastery, row.stability, days=days)
    item = row.item
    overdue = overdue_ratio(item.due_at, now, item.interval_days)
    return ReviewItemOut(
        id=item.id,
        kp_id=item.kp_id,
        kp_name=row.kp_name,
        subject_id=row.subject_id,
        ref_type=item.ref_type,
        ref_id=item.ref_id,
        ref_title=detail.title,
        ref_available=detail.available,
        due_at=item.due_at,
        interval_days=item.interval_days,
        priority=review_priority(mastery_t, overdue, row.exam_weight),
        estimated_minutes=estimated_minutes(item.ref_type, detail.difficulty),
        mastery=round(row.mastery, 3),
        mastery_t=mastery_t,
        stability=round(row.stability, 2),
        attempts=row.attempts,
        overdue_days=overdue_days(item.due_at, now),
        low_mastery=mastery_t < LOW_MASTERY,
        done_at=item.done_at,
    )


def _empty_today(now: datetime, tz: ZoneInfo) -> ReviewTodayOut:
    _, _, local_date = local_bounds(now, tz)
    return ReviewTodayOut(
        date=local_date.isoformat(),
        timezone=str(tz),
        items=[],
        item_count=0,
        total_minutes=0,
        cap_minutes=get_settings().review_daily_minutes,
        truncated_count=None,
    )


def get_today(
    session: Session, *, user_id: int, now: datetime | None = None
) -> ReviewTodayOut:
    moment = now or datetime.now(timezone.utc)
    tz = _timezone()
    _, next_start, local_date = local_bounds(moment, tz)
    rows = _load_today_snapshots(session, user_id=user_id, next_start=next_start)
    details = _ref_details(session, user_id=user_id, rows=rows)
    items = [
        _item_out(row, details[(row.item.ref_type, row.item.ref_id)], now=moment)
        for row in rows
    ]
    items.sort(key=lambda item: (-item.priority, item.mastery_t, item.kp_id))
    return ReviewTodayOut(
        date=local_date.isoformat(),
        timezone=str(tz),
        items=items,
        item_count=len(items),
        total_minutes=sum(item.estimated_minutes for item in items),
        cap_minutes=get_settings().review_daily_minutes,
        truncated_count=None,
    )


def refresh_user(
    session: Session, *, user_id: int, now: datetime | None = None
) -> ReviewTodayOut:
    moment = now or datetime.now(timezone.utc)
    tz = _timezone()
    day_start, next_start, _ = local_bounds(moment, tz)
    snapshots = _load_mastery_snapshots(session, user_id)
    if not snapshots:
        return _empty_today(moment, tz)

    plans: list[ItemPlan] = []
    refs = _load_ref_choices(
        session, user_id=user_id, kp_ids=[snap.kp_id for snap in snapshots]
    )
    for snap in snapshots:
        days = 0.0
        if snap.last_practice_at is not None:
            days = max(0.0, (moment - snap.last_practice_at).total_seconds() / 86400.0)
        mastery_t = decayed_mastery(snap.mastery, snap.stability, days=days)
        due = snap.due_at or moment
        if not is_candidate(mastery_t, due, next_start=next_start):
            continue
        ref = refs.get(snap.kp_id)
        if ref is None:
            continue
        low = mastery_t < LOW_MASTERY
        effective_due = day_start if low and due >= next_start else due
        interval = review_interval_days(snap.stability, mastery_t)
        plans.append(
            ItemPlan(
                kp_id=snap.kp_id,
                kp_name=snap.kp_name,
                subject_id=snap.subject_id,
                ref_type=ref.ref_type,
                ref_id=ref.ref_id,
                due_at=effective_due,
                interval_days=interval,
                priority=review_priority(
                    mastery_t,
                    overdue_ratio(effective_due, moment, interval),
                    snap.exam_weight,
                ),
                estimated_minutes=estimated_minutes(ref.ref_type, ref.difficulty),
                mastery=snap.mastery,
                mastery_t=mastery_t,
                stability=snap.stability,
                attempts=snap.attempts,
                overdue_days=overdue_days(effective_due, moment),
                low_mastery=low,
            )
        )

    existing = _load_items(session, user_id)
    eligible: list[ItemPlan] = []
    for plan in plans:
        row = existing.get(plan.kp_id)
        if row is not None:
            if row.done_at is not None and row.done_at >= day_start:
                continue
            # later/超限已顺延到次日：同日再刷新不得被“弱项天天出现”拉回今天
            if row.done_at is None and row.due_at >= next_start:
                continue
        eligible.append(plan)

    selected, deferred = select_capped(eligible, get_settings().review_daily_minutes)
    selected_ids = {plan.kp_id for plan in selected}
    for plan in eligible:
        row = existing.get(plan.kp_id)
        clear_done = bool(row is not None and row.done_at is not None)
        if plan.kp_id not in selected_ids:
            plan = replace(plan, due_at=next_start)
        _upsert_item(session, user_id=user_id, plan=plan, clear_done=clear_done)
    session.flush()
    today = get_today(session, user_id=user_id, now=moment)
    return today.model_copy(update={"truncated_count": len(deferred)})


def mark_item(
    session: Session,
    *,
    user_id: int,
    item_id: int,
    action: str,
    now: datetime | None = None,
) -> ReviewItemOut:
    if action not in {ACTION_DONE, ACTION_SKIP, ACTION_LATER}:
        raise InvalidParamError("未知复习操作")
    item = session.scalar(
        select(ReviewItem).where(
            ReviewItem.id == item_id, ReviewItem.user_id == user_id
        )
    )
    if item is None:
        raise NotFoundError("复习项不存在")
    if item.done_at is not None:
        raise ConflictError("该复习项已完成")
    moment = now or datetime.now(timezone.utc)
    _, next_start, _ = local_bounds(moment, _timezone())
    if action == ACTION_LATER:
        item.due_at = next_start
    else:
        item.done_at = moment
    session.flush()
    snapshot = _load_item_snapshot(session, user_id=user_id, item_id=item_id)
    if snapshot is None:
        raise NotFoundError("复习项不存在")
    detail = _ref_details(session, user_id=user_id, rows=[snapshot])[
        (snapshot.item.ref_type, snapshot.item.ref_id)
    ]
    return _item_out(snapshot, detail, now=moment)
