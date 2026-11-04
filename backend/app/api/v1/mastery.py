"""S4-7 掌握度接口：本人重算 + 本人列表（API.md §4.6）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.kp import MasteryPage, MasteryRecomputeOut
from app.services import mastery_service
from app.utils.pagination import PageParams, SortParams, page_params, sort_params

router = APIRouter(prefix="/kp/mastery", tags=["mastery"])


@router.post(
    "/recompute", response_model=Envelope[MasteryRecomputeOut], summary="重算掌握度"
)
def recompute_mastery(
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[MasteryRecomputeOut]:
    result = mastery_service.recompute_user(session, user_id=current_user.id)
    return Envelope(
        trace_id=get_trace_id(),
        data=MasteryRecomputeOut(
            events_replayed=result.events_replayed,
            rows_built=result.rows_built,
            skipped_no_kp=result.skipped_no_kp,
        ),
    )


@router.get("", response_model=Envelope[MasteryPage], summary="我的掌握度")
def list_my_mastery(
    subject_id: int | None = Query(None, ge=1, description="学科 id"),
    page: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[MasteryPage]:
    return Envelope(
        trace_id=get_trace_id(),
        data=mastery_service.list_mastery(
            session,
            user_id=current_user.id,
            subject_id=subject_id,
            page=page,
            sort=sort,
        ),
    )