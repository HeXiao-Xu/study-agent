"""S4-8 错题统计看板：本人错题的窗口聚合（状态/错因/知识点/趋势）。

全部走 SQL 聚合（9 条单行或分组语句），Python 只做「按天补零 + DTO 组装」，
不允许逐行查库。窗口与补零是纯函数，可脱离数据库断言。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import Date, func, literal_column, select
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidParamError
from app.models.enums import MISTAKE_STATUSES, MistakeStatus
from app.models.knowledge_point import KnowledgePoint
from app.models.mastery import Mastery
from app.models.mistake import Mistake
from app.models.mistake_analysis import MistakeAnalysis
from app.models.question_kp import QuestionKp
from app.schemas.stats import (
    StatsCauseCountOut,
    StatsOverviewOut,
    StatsRangeOut,
    StatsStatusCountOut,
    StatsSummaryOut,
    StatsTopKpOut,
    StatsTrendPointOut,
)
from app.services import mastery_service

RANGES: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}
DEFAULT_RANGE = "30d"
TOP_KP_LIMIT = 10


@dataclass(frozen=True, slots=True)
class Window:
    key: str
    days: int
    start: datetime
    end: datetime
    dates: list[date]


def build_window(range_key: str, *, now: datetime | None = None) -> Window:
    """窗口 = 今天往前 N-1 天的 00:00 UTC ~ 现在；按天分桶用 UTC。"""
    if range_key not in RANGES:
        options = "、".join(RANGES)
        raise InvalidParamError(f"不支持的统计窗口：{range_key}（可选：{options}）")
    days = RANGES[range_key]
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    last_day = moment.date()
    dates = [last_day - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
    start = datetime.combine(dates[0], time.min, tzinfo=timezone.utc)
    return Window(key=range_key, days=days, start=start, end=moment, dates=dates)


def fill_days(
    rows: Mapping[date, int], dates: Sequence[date]
) -> list[tuple[date, int]]:
    """缺的天补 0：折线不能断在没数据的那天。"""
    return [(day, int(rows.get(day, 0))) for day in dates]


def _day(column: Any) -> Any:
    """按天分桶。

    `date_trunc` 的 'day' 必须走字面量：写成 Python 字符串会被编译成绑定参数，
    PG 认不出 SELECT 与 GROUP BY 里是同一个表达式（实测 GroupingError）。
    """
    return func.date_trunc(literal_column("'day'"), column).cast(Date)


def overview(
    session: Session,
    *,
    user_id: int,
    range_key: str = DEFAULT_RANGE,
    now: datetime | None = None,
) -> StatsOverviewOut:
    window = build_window(range_key, now=now)
    in_window = [
        Mistake.user_id == user_id,
        Mistake.created_at >= window.start,
        Mistake.created_at <= window.end,
    ]

    status_rows = session.execute(
        select(Mistake.status, func.count()).where(*in_window).group_by(Mistake.status)
    ).all()
    counts = {status: int(count) for status, count in status_rows}
    by_status = [
        StatsStatusCountOut(status=status, count=counts.get(status, 0))
        for status in MISTAKE_STATUSES
    ]
    analyzed = int(
        session.scalar(
            select(func.count(func.distinct(MistakeAnalysis.mistake_id)))
            .join(Mistake, Mistake.id == MistakeAnalysis.mistake_id)
            .where(*in_window)
        )
        or 0
    )
    with_kp = int(
        session.scalar(
            select(func.count(func.distinct(Mistake.id)))
            .join(QuestionKp, QuestionKp.question_id == Mistake.question_id)
            .where(*in_window)
        )
        or 0
    )
    mastery_rows = int(
        session.scalar(
            select(func.count()).select_from(Mastery).where(Mastery.user_id == user_id)
        )
        or 0
    )

    cause_rows = session.execute(
        select(MistakeAnalysis.cause_type, func.count())
        .join(Mistake, Mistake.id == MistakeAnalysis.mistake_id)
        .where(*in_window)
        .group_by(MistakeAnalysis.cause_type)
        # 并列时不排序会让图例每次刷新都换位置
        .order_by(func.count().desc(), MistakeAnalysis.cause_type)
    ).all()

    kp_count = func.count(func.distinct(Mistake.id))
    kp_rows = session.execute(
        select(QuestionKp.kp_id, KnowledgePoint.name, kp_count)
        .join(Mistake, Mistake.question_id == QuestionKp.question_id)
        .join(KnowledgePoint, KnowledgePoint.id == QuestionKp.kp_id)
        .where(*in_window)
        .group_by(QuestionKp.kp_id, KnowledgePoint.name)
        .order_by(kp_count.desc(), QuestionKp.kp_id)
        .limit(TOP_KP_LIMIT)
    ).all()
    mastered = mastery_service.mastery_values(
        session,
        user_id=user_id,
        kp_ids=[int(kp_id) for kp_id, _name, _count in kp_rows],
        now=window.end,
    )

    new_rows = session.execute(
        select(_day(Mistake.created_at), func.count())
        .where(*in_window)
        .group_by(_day(Mistake.created_at))
    ).all()
    # 已掌握按天分组不取窗口：窗口开始前就掌握的那些要算进累计起点
    mastered_rows = session.execute(
        select(_day(Mistake.last_review_at), func.count())
        .where(
            Mistake.user_id == user_id,
            Mistake.status == MistakeStatus.MASTERED.value,
            Mistake.last_review_at.is_not(None),
        )
        .group_by(_day(Mistake.last_review_at))
    ).all()
    daily_new = {day: int(count) for day, count in new_rows}
    daily_mastered = {day: int(count) for day, count in mastered_rows}
    running = sum(
        count for day, count in daily_mastered.items() if day < window.dates[0]
    )
    trend: list[StatsTrendPointOut] = []
    for day, new_mistakes in fill_days(daily_new, window.dates):
        running += daily_mastered.get(day, 0)
        trend.append(
            StatsTrendPointOut(date=day, new_mistakes=new_mistakes, mastered=running)
        )

    return StatsOverviewOut(
        range=StatsRangeOut(key=window.key, from_=window.dates[0], to=window.dates[-1]),
        summary=StatsSummaryOut(
            total=sum(counts.values()),
            pending=counts.get(MistakeStatus.TODO.value, 0),
            corrected=counts.get(MistakeStatus.CORRECTED.value, 0),
            mastered=counts.get(MistakeStatus.MASTERED.value, 0),
            analyzed=analyzed,
            with_kp=with_kp,
            mastery_rows=mastery_rows,
        ),
        by_status=by_status,
        by_cause=[
            StatsCauseCountOut(cause_type=cause, count=int(count))
            for cause, count in cause_rows
        ],
        top_kps=[
            StatsTopKpOut(
                kp_id=int(kp_id),
                kp_name=name,
                count=int(count),
                mastery=mastered.get(int(kp_id)),
            )
            for kp_id, name, count in kp_rows
        ],
        trend=trend,
    )