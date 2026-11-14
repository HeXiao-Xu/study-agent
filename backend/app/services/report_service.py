"""S5-6 学习报告：窗口聚合、模块雷达、热力节点、趋势与周报统计。

纯函数与 DB 用例分开；本模块不 commit，由路由/调用方提交。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime

from app.schemas.report import ReportTrendPointOut
from app.services import stats_service

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