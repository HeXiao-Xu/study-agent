"""S2-2 认证业务：注册、登录、签发令牌（spec §5）。

一个用例一个事务：注册失败必须 rollback 后再抛，不能留下半插入状态。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import CODE_CONFLICT, AppError, AuthError
from app.core.security import (
    create_access_token,
    dummy_password_hash,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import RegisterRequest, TokenOut, UserOut


class UserAlreadyExistsError(AppError):
    def __init__(self, message: str = "用户名已存在") -> None:
        super().__init__(message, code=CODE_CONFLICT, http_status=409)


def register_user(session: Session, payload: RegisterRequest) -> User:
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        nickname=payload.nickname,
        grade=payload.grade,
        role=payload.role,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise UserAlreadyExistsError() from exc
    session.refresh(user)
    return user


def authenticate_user(session: Session, *, username: str, password: str) -> User:
    user = session.scalar(select(User).where(User.username == username))
    if user is None:
        # 用户不存在也做一次哈希校验：响应时间不因“账号是否存在”而不同
        verify_password(password, dummy_password_hash())
        raise AuthError("用户名或密码错误")
    if not verify_password(password, user.password_hash):
        raise AuthError("用户名或密码错误")
    return user


def issue_token_for(user: User) -> TokenOut:
    issued = create_access_token(user_id=user.id, role=user.role)
    return TokenOut(
        access_token=issued.token,
        expires_in=issued.expires_in,
        user=UserOut.model_validate(user),
    )