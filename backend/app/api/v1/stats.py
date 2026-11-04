"""S4-8 统计看板接口（API.md §4.7）：本人错题四维聚合，只读。"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.stats import StatsOverviewOut
from app.services import stats_service

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get(
    "/overview", response_model=Envelope[StatsOverviewOut], summary="错题统计看板"
)
def stats_overview(
    range_: Literal["7d", "30d", "90d"] = Query(
        stats_service.DEFAULT_RANGE, alias="range", description="统计窗口"
    ),
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[StatsOverviewOut]:
    return Envelope(
        trace_id=get_trace_id(),
        data=stats_service.overview(session, user_id=current_user.id, range_key=range_),
    )