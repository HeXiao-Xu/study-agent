"""S4-7 掌握度模型（方案 §6.6）。

公式定位是「参考 SM-2 / FSRS 的工程化简化」：参数是工程取值，不是拟合结果。
本模块前半部分全是纯函数，便于单测与手推；DB 用例在文件末尾。
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

if TYPE_CHECKING:  # pragma: no cover
    from app.models.mastery import Mastery

    from app.schemas.kp import MasteryPage
    from app.utils.pagination import PageParams, SortParams

K0 = 0.35
"""单次作答的基础更新幅度；难题带来更小的更新（避免一题定生死）。"""

INITIAL_STABILITY = 2.0
STABILITY_GROW = 1.8
STABILITY_SHRINK = 0.5
STABILITY_MAX = 60.0
STABILITY_MIN = 1.0

INTERVAL_MIN_DAYS = 1
INTERVAL_MAX_DAYS = 30

MASTERY_PRECISION = 3
STABILITY_PRECISION = 2


@dataclass(frozen=True, slots=True)
class MasteryState:
    """掌握度的一次快照；不可变，方便「读 → 算 → 写」而不共享状态。"""

    mastery: float
    attempts: int
    correct_cnt: int
    stability: float
    last_practice_at: datetime | None = None
    due_at: datetime | None = None


NEW_STATE = MasteryState(
    mastery=0.0,
    attempts=0,
    correct_cnt=0,
    stability=INITIAL_STABILITY,
    last_practice_at=None,
    due_at=None,
)


def effective_k(difficulty: int) -> float:
    """K_eff = K0 / difficulty；难度越界按 1..5 收敛，不让脏数据把公式炸掉。"""
    safe = min(5, max(1, int(difficulty)))
    return K0 / safe


def next_mastery(mastery: float, s: float, k: float) -> float:
    """M ← clamp(M + K_eff·(s − M), 0, 1)。"""
    updated = mastery + k * (s - mastery)
    return round(min(1.0, max(0.0, updated)), MASTERY_PRECISION)


def next_stability(stability: float, s: float) -> float:
    """答对放大间隔、答错缩短；半对（s=0.5）方案没定义，按「不增不减」处理。"""
    if s >= 1.0:
        return round(min(STABILITY_MAX, stability * STABILITY_GROW), STABILITY_PRECISION)
    if s <= 0.0:
        return round(max(STABILITY_MIN, stability * STABILITY_SHRINK), STABILITY_PRECISION)
    return round(stability, STABILITY_PRECISION)


def decayed_mastery(mastery: float, stability: float, *, days: float) -> float:
    """M_t = M·exp(−Δt/S)；未来时间/负间隔按 0 天处理（时钟回拨不该抬高掌握度）。"""
    if days <= 0:
        return round(mastery, MASTERY_PRECISION)
    safe_stability = max(stability, 0.01)
    return round(mastery * math.exp(-days / safe_stability), MASTERY_PRECISION)


def review_interval_days(stability: float, mastery_t: float) -> int:
    """interval = clamp(round(S·M_t), 1, 30) 天。"""
    raw = int(round(stability * mastery_t))
    return max(INTERVAL_MIN_DAYS, min(INTERVAL_MAX_DAYS, raw))


def next_state(
    state: MasteryState, *, s: float, difficulty: int, now: datetime
) -> MasteryState:
    """一次作答后的新状态；刚作答时 Δt=0，到期间隔用当前 M 而不是衰减后的值。"""
    mastery = next_mastery(state.mastery, s, effective_k(difficulty))
    stability = next_stability(state.stability, s)
    due_at = now + timedelta(days=review_interval_days(stability, mastery))
    return MasteryState(
        mastery=mastery,
        attempts=state.attempts + 1,
        correct_cnt=state.correct_cnt + (1 if s >= 1.0 else 0),
        stability=stability,
        last_practice_at=now,
        due_at=due_at,
    )

# --------------------------------------------------------------------------
# DB 用例：读行 → 纯函数 → 写回
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RecomputeResult:
    events_replayed: int
    rows_built: int
    skipped_no_kp: int


STATUS_TO_S: dict[str, float] = {
    "待订正": 0.0,
    "已订正": 0.5,
    "已掌握": 1.0,
}
"""回放口径：错题状态折算成一次作答结果（spec §3.2）。"""


def _to_state(row: Mastery) -> MasteryState:
    return MasteryState(
        mastery=float(row.mastery),
        attempts=row.attempts,
        correct_cnt=row.correct_cnt,
        stability=float(row.stability),
        last_practice_at=row.last_practice_at,
        due_at=row.due_at,
    )


def _apply(row: Mastery, state: MasteryState) -> None:
    row.mastery = Decimal(str(state.mastery))
    row.attempts = state.attempts
    row.correct_cnt = state.correct_cnt
    row.stability = Decimal(str(state.stability))
    row.last_practice_at = state.last_practice_at
    row.due_at = state.due_at


def record_attempts(
    session: Session,
    *,
    user_id: int,
    kp_ids: Sequence[int],
    s: float,
    difficulty: int,
    now: datetime | None = None,
) -> list[Mastery]:
    """一次作答更新多个知识点；缺行则懒创建。**不 commit**，由调用方统一提交。"""
    from app.models.mastery import Mastery

    unique_ids = sorted({int(kp_id) for kp_id in kp_ids})
    if not unique_ids:
        return []
    moment = now or datetime.now(timezone.utc)
    existing = {
        row.kp_id: row
        for row in session.scalars(
            select(Mastery).where(
                Mastery.user_id == user_id, Mastery.kp_id.in_(unique_ids)
            )
        )
    }
    updated: list[Mastery] = []
    for kp_id in unique_ids:
        row = existing.get(kp_id)
        if row is None:
            row = Mastery(
                user_id=user_id,
                kp_id=kp_id,
                mastery=Decimal(str(NEW_STATE.mastery)),
                attempts=0,
                correct_cnt=0,
                stability=Decimal(str(NEW_STATE.stability)),
            )
            session.add(row)
            state = NEW_STATE
        else:
            state = _to_state(row)
        _apply(row, next_state(state, s=s, difficulty=difficulty, now=moment))
        updated.append(row)
    session.flush()
    return updated


def recompute_user(
    session: Session, *, user_id: int, now: datetime | None = None
) -> RecomputeResult:
    """按时间序回放本人错题事件，覆盖式重建掌握度（幂等）。"""
    from app.models.mastery import Mastery
    from app.models.mistake import Mistake
    from app.models.question import Question
    from app.models.question_kp import QuestionKp

    event_at = func.coalesce(Mistake.last_review_at, Mistake.created_at)
    rows = session.execute(
        select(
            Mistake.id,
            Mistake.status,
            event_at.label("event_at"),
            Question.difficulty,
            QuestionKp.kp_id,
        )
        .join(Question, Question.id == Mistake.question_id)
        .join(QuestionKp, QuestionKp.question_id == Mistake.question_id)
        .where(Mistake.user_id == user_id)
    ).all()
    total_mistakes = int(
        session.scalar(
            select(func.count()).select_from(Mistake).where(Mistake.user_id == user_id)
        )
        or 0
    )
    states: dict[int, MasteryState] = {}
    ordered = sorted(rows, key=lambda row: (row[2], row[0], row[4]))
    for _mistake_id, status, moment, difficulty, kp_id in ordered:
        state = states.get(kp_id, NEW_STATE)
        states[kp_id] = next_state(
            state,
            s=STATUS_TO_S.get(status, 0.0),
            difficulty=int(difficulty or 3),
            now=moment,
        )
    session.execute(delete(Mastery).where(Mastery.user_id == user_id))
    for kp_id, state in sorted(states.items()):
        row = Mastery(
            user_id=user_id,
            kp_id=kp_id,
            mastery=Decimal("0"),
            attempts=0,
            correct_cnt=0,
            stability=Decimal("2"),
        )
        _apply(row, state)
        session.add(row)
    session.commit()
    replayed_ids = {row[0] for row in ordered}
    return RecomputeResult(
        events_replayed=len(ordered),
        rows_built=len(states),
        skipped_no_kp=max(0, total_mistakes - len(replayed_ids)),
    )


def list_mastery(
    session: Session,
    *,
    user_id: int,
    subject_id: int | None,
    page: PageParams,
    sort: SortParams,
) -> MasteryPage:
    """本人已评估的掌握度；`mastery_t` 按当前时间折算。"""
    from fastapi_pagination import Params
    from fastapi_pagination.ext.sqlalchemy import paginate as paginate_sa

    from app.models.knowledge_point import KnowledgePoint
    from app.models.mastery import Mastery
    from app.schemas.kp import MasteryOut, MasteryPage
    from app.utils.pagination import apply_sort

    columns = {
        "mastery": Mastery.mastery,
        "due_at": Mastery.due_at,
        "attempts": Mastery.attempts,
        "kp_id": Mastery.kp_id,
    }
    stmt = (
        select(Mastery, KnowledgePoint.name, KnowledgePoint.subject_id)
        .join(KnowledgePoint, KnowledgePoint.id == Mastery.kp_id)
        .where(Mastery.user_id == user_id)
    )
    if subject_id is not None:
        stmt = stmt.where(KnowledgePoint.subject_id == subject_id)
    # 默认「最薄弱优先」，显式传 sort 才用调用方的方向
    stmt = apply_sort(
        stmt,
        sort_by=sort.sort_by or "mastery",
        order=sort.order if sort.sort_by else "asc",
        allowed=columns,
        default_sort="mastery",
    )
    # mastery 同值的行很多，补 kp_id 兜底避免翻页重复/漏行（S4-5 同类坑）
    stmt = stmt.order_by(Mastery.kp_id.asc())
    data = paginate_sa(session, stmt, params=Params(page=page.page, size=page.page_size))
    now = datetime.now(timezone.utc)
    items: list[MasteryOut] = []
    for row, kp_name, kp_subject_id in data.items:
        days = 0.0
        if row.last_practice_at is not None:
            days = max(0.0, (now - row.last_practice_at).total_seconds() / 86400.0)
        items.append(
            MasteryOut(
                kp_id=row.kp_id,
                kp_name=kp_name,
                subject_id=kp_subject_id,
                mastery=float(row.mastery),
                mastery_t=decayed_mastery(
                    float(row.mastery), float(row.stability), days=days
                ),
                attempts=row.attempts,
                correct_cnt=row.correct_cnt,
                stability=float(row.stability),
                last_practice_at=row.last_practice_at,
                due_at=row.due_at,
            )
        )
    return MasteryPage(items=items, total=data.total, page=data.page, page_size=data.size)


def mastery_values(
    session: Session,
    *,
    user_id: int,
    kp_ids: Sequence[int],
    now: datetime | None = None,
) -> dict[int, float]:
    """批量取有效掌握度 M_t；无行的知识点不出现在结果里（= 未评估）。"""
    from app.models.mastery import Mastery

    unique_ids = sorted({int(kp_id) for kp_id in kp_ids})
    if not unique_ids:
        return {}
    moment = now or datetime.now(timezone.utc)
    rows = session.execute(
        select(
            Mastery.kp_id, Mastery.mastery, Mastery.stability, Mastery.last_practice_at
        ).where(Mastery.user_id == user_id, Mastery.kp_id.in_(unique_ids))
    ).all()
    values: dict[int, float] = {}
    for kp_id, mastery, stability, last_practice_at in rows:
        days = 0.0
        if last_practice_at is not None:
            days = max(0.0, (moment - last_practice_at).total_seconds() / 86400.0)
        values[int(kp_id)] = decayed_mastery(
            float(mastery), float(stability), days=days
        )
    return values
