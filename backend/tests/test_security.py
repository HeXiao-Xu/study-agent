"""S2-2 认证原语测试：Argon2id 哈希与 HS256 JWT（spec §9.1）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import Settings
from app.core.exceptions import AuthError
from app.core.security import (
    create_access_token,
    decode_access_token,
    ensure_auth_configured,
    hash_password,
    verify_password,
)

_SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"


def _settings(**overrides) -> Settings:
    data = {"auth_secret_key": _SECRET}
    data.update(overrides)
    return Settings(_env_file=None, **data)


def test_hash_password_is_not_plaintext_and_salted() -> None:
    first = hash_password("test-pass-123")
    second = hash_password("test-pass-123")
    assert first != "test-pass-123"
    assert first != second
    assert first.startswith("$argon2")


def test_verify_password_accepts_correct_and_rejects_wrong() -> None:
    hashed = hash_password("test-pass-123")
    assert verify_password("test-pass-123", hashed) is True
    assert verify_password("wrong-pass-1", hashed) is False


def test_verify_password_returns_false_on_broken_hash() -> None:
    assert verify_password("test-pass-123", "definitely-not-a-hash") is False


def test_token_roundtrip_carries_user_id_role_and_exp() -> None:
    settings = _settings()
    issued = create_access_token(user_id=7, role="teacher", settings=settings)
    claims = decode_access_token(issued.token, settings=settings)
    assert claims.user_id == 7
    assert claims.role == "teacher"
    assert claims.exp.tzinfo is not None
    assert claims.exp > datetime.now(timezone.utc)
    assert issued.expires_in == 1440 * 60


def test_expired_token_raises_auth_error() -> None:
    settings = _settings()
    issued = create_access_token(
        user_id=1, role="student", expires_delta=timedelta(seconds=-5), settings=settings
    )
    with pytest.raises(AuthError) as excinfo:
        decode_access_token(issued.token, settings=settings)
    assert "过期" in excinfo.value.message


def test_token_signed_with_other_secret_is_rejected() -> None:
    issued = create_access_token(
        user_id=1,
        role="student",
        settings=_settings(auth_secret_key="other-secret-0123456789abcdef0123456789"),
    )
    with pytest.raises(AuthError) as excinfo:
        decode_access_token(issued.token, settings=_settings())
    assert excinfo.value.message == "无效的认证凭据"


def test_tampered_token_is_rejected() -> None:
    issued = create_access_token(user_id=1, role="student", settings=_settings())
    with pytest.raises(AuthError):
        decode_access_token(issued.token[:-3] + "abc", settings=_settings())


def test_unknown_role_in_token_is_rejected() -> None:
    settings = _settings()
    issued = create_access_token(user_id=1, role="hacker", settings=settings)
    with pytest.raises(AuthError) as excinfo:
        decode_access_token(issued.token, settings=settings)
    assert excinfo.value.message == "无效的认证凭据"


def test_ensure_auth_configured_rejects_empty_secret() -> None:
    with pytest.raises(RuntimeError):
        ensure_auth_configured(Settings(_env_file=None, auth_secret_key=""))


def test_ensure_auth_configured_accepts_secret() -> None:
    ensure_auth_configured(_settings())