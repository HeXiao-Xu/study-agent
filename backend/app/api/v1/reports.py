"""S5-6 学习报告：雷达/热力/趋势 + LLM 周报（API.md §9）。"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.cache import get_cache
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.report import ReportOverviewOut, WeeklyReportOut
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get(
    "/mastery", response_model=Envelope[ReportOverviewOut], summary="学习报告图表数据"
)
def report_mastery(
    range_: Literal["7d", "30d", "90d"] = Query(
        report_service.DEFAULT_RANGE, alias="range", description="趋势窗口"
    ),
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[ReportOverviewOut]:
    return Envelope(
        trace_id=get_trace_id(),
        data=report_service.get_overview(
            session, user_id=current_user.id, range_key=range_
        ),
    )


@router.get(
    "/weekly",
    response_model=Envelope[WeeklyReportOut | None],
    summary="读取当天已生成的周报",
)
def get_weekly(
    current_user: User = Depends(require_role("student")),
) -> Envelope[WeeklyReportOut | None]:
    return Envelope(
        trace_id=get_trace_id(),
        data=report_service.load_weekly_report(
            get_cache(), user_id=current_user.id
        ),
    )


@router.post(
    "/weekly", response_model=Envelope[WeeklyReportOut], summary="生成学习周报"
)
def generate_weekly(
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[WeeklyReportOut]:
    report = report_service.generate_weekly(session, user_id=current_user.id)
    report_service.store_weekly_report(
        get_cache(), user_id=current_user.id, report=report
    )
    return Envelope(trace_id=get_trace_id(), data=report)
