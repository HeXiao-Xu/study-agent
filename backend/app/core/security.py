"""S2-2 认证原语：Argon2id 口令哈希 + HS256 JWT（spec §4）。

为什么把原语与业务分开：哈希/JWT 是纯函数，能脱离数据库单测；
service 只负责“查库 + 组装 + 事务”，router 只负责壳。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthError
from app.models.enums import UserRole

_PASSWORD_HASH = PasswordHash.recommended()
_VALID_ROLES = frozenset(member.value for member in UserRole)


@dataclass(frozen=True)
class IssuedToken:
    token: str
    expires_in: int


@dataclass(frozen=True)
class TokenClaims:
    user_id: int
    role: str
    exp: datetime


def hash_password(password: str) -> str:
    return _PASSWORD_HASH.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """哈希串损坏/格式不认识 → False（不能让登录接口 500）。

    pwdlib 的 UnknownHashError 继承自 Exception（不是 ValueError）；
    argon2 的 InvalidHashError 继承 ValueError，两个都要接住。
    """
    try:
        return _PASSWORD_HASH.verify(password, password_hash)
    except (UnknownHashError, ValueError, TypeError):
        return False


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    """登录用户不存在时也跑一次校验，抹平“存在/不存在”的响应时间差。"""
    return hash_password("dummy-password-for-timing-equalization")


def _secret(settings: Settings) -> str:
    if not settings.auth_secret_key:
        raise RuntimeError(
            "AUTH_SECRET_KEY 未配置：请在 .env 设置随机密钥（见 .env.example）"
        )
    return settings.auth_secret_key


def ensure_auth_configured(settings: Settings | None = None) -> None:
    """启动时快速失败，避免无密钥的服务跑起来后才在登录处 500。"""
    _secret(settings or get_settings())


def create_access_token(
    *,
    user_id: int,
    role: str,
    expires_delta: timedelta | None = None,
    settings: Settings | None = None,
) -> IssuedToken:
    current = settings or get_settings()
    now = datetime.now(timezone.utc)
    expires = now + (
        expires_delta or timedelta(minutes=current.auth_access_token_expire_minutes)
    )
    payload = {"sub": str(user_id), "role": role, "iat": now, "exp": expires}
    token = jwt.encode(payload, _secret(current), algorithm=current.auth_algorithm)
    return IssuedToken(token=token, expires_in=int((expires - now).total_seconds()))


def decode_access_token(token: str, *, settings: Settings | None = None) -> TokenClaims:
    current = settings or get_settings()
    try:
        payload = jwt.decode(
            token,
            _secret(current),
            algorithms=[current.auth_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("无效的认证凭据") from exc

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError("无效的认证凭据") from exc

    role = payload.get("role")
    if role not in _VALID_ROLES:
        raise AuthError("无效的认证凭据")

    exp_raw = payload.get("exp")
    if not isinstance(exp_raw, (int, float)):
        raise AuthError("无效的认证凭据")
    return TokenClaims(
        user_id=user_id,
        role=role,
        exp=datetime.fromtimestamp(exp_raw, tz=timezone.utc),
    )