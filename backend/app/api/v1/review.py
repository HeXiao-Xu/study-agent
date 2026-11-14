"""S5-5 复习清单接口（API.md §9）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.review import ReviewItemOut, ReviewTodayOut
from app.services import review_service

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/today", response_model=Envelope[ReviewTodayOut], summary="今日复习清单")
def get_today(
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[ReviewTodayOut]:
    return Envelope(
        trace_id=get_trace_id(),
        data=review_service.get_today(session, user_id=current_user.id),
    )


@router.post("/refresh", response_model=Envelope[ReviewTodayOut], summary="刷新今日清单")
def refresh(
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[ReviewTodayOut]:
    data = review_service.refresh_user(session, user_id=current_user.id)
    session.commit()
    return Envelope(trace_id=get_trace_id(), data=data)


def _mark(
    item_id: int, action: str, current_user: User, session: Session
) -> Envelope[ReviewItemOut]:
    data = review_service.mark_item(
        session, user_id=current_user.id, item_id=item_id, action=action
    )
    session.commit()
    return Envelope(trace_id=get_trace_id(), data=data)


@router.post(
    "/items/{item_id}/done",
    response_model=Envelope[ReviewItemOut],
    summary="完成复习项",
)
def done(
    item_id: int,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[ReviewItemOut]:
    return _mark(item_id, "done", current_user, session)


@router.post(
    "/items/{item_id}/skip",
    response_model=Envelope[ReviewItemOut],
    summary="跳过复习项",
)
def skip(
    item_id: int,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[ReviewItemOut]:
    return _mark(item_id, "skip", current_user, session)


@router.post(
    "/items/{item_id}/later",
    response_model=Envelope[ReviewItemOut],
    summary="稍后复习",
)
def later(
    item_id: int,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[ReviewItemOut]:
    return _mark(item_id, "later", current_user, session)