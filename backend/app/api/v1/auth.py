"""S2-2 认证接口：注册 / 登录 / 当前用户（spec §3）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.context import get_trace_id
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenOut, UserOut
from app.schemas.common import Envelope
from app.services.auth_service import authenticate_user, issue_token_for, register_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    status_code=201,
    response_model=Envelope[UserOut],
    summary="注册（student/teacher/parent，admin 不可自助注册）",
)
def register(
    payload: RegisterRequest, session: Session = Depends(get_db)
) -> Envelope[UserOut]:
    user = register_user(session, payload)
    return Envelope[UserOut](trace_id=get_trace_id(), data=UserOut.model_validate(user))


@router.post("/login", response_model=Envelope[TokenOut], summary="登录")
def login(
    payload: LoginRequest, session: Session = Depends(get_db)
) -> Envelope[TokenOut]:
    user = authenticate_user(session, username=payload.username, password=payload.password)
    return Envelope[TokenOut](trace_id=get_trace_id(), data=issue_token_for(user))


@router.get("/me", response_model=Envelope[UserOut], summary="当前登录用户")
def me(current_user: User = Depends(get_current_user)) -> Envelope[UserOut]:
    return Envelope[UserOut](
        trace_id=get_trace_id(), data=UserOut.model_validate(current_user)
    )