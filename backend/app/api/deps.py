"""请求级依赖：数据库 Session 与当前登录用户（spec §6.1）。

S2-3 的 require_role/require_student_access 直接在本文件的
get_current_user 之上组合，不再自己解析 token。
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import new_session
from app.core.exceptions import AuthError
from app.core.security import decode_access_token
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Iterator[Session]:
    session = new_session()
    try:
        yield session
    finally:
        session.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthError("未提供认证凭据")
    claims = decode_access_token(credentials.credentials)
    user = session.scalar(select(User).where(User.id == claims.user_id))
    if user is None:
        raise AuthError("账号不存在或已被删除")
    return user