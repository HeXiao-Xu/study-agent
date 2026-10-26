"""S2-2 认证服务测试：fake session 覆盖注册/登录/签发（spec §9.2）。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.core import security
from app.core.config import Settings
from app.core.exceptions import AuthError
from app.core.security import decode_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import RegisterRequest
from app.services import auth_service
from app.services.auth_service import (
    UserAlreadyExistsError,
    authenticate_user,
    issue_token_for,
    register_user,
)


class FakeSession:
    def __init__(self, *, user: User | None = None, commit_error: Exception | None = None) -> None:
        self.user = user
        self.commit_error = commit_error
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.refreshed: list[object] = []
        self.statements: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, instance: object) -> None:
        self.refreshed.append(instance)
        if getattr(instance, "id", None) is None:
            instance.id = 1
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)

    def scalar(self, statement: object) -> User | None:
        self.statements.append(statement)
        return self.user


def _payload(**overrides) -> RegisterRequest:
    data = {
        "username": "Test_User_1",
        "password": "test-pass-123",
        "nickname": "测试用户_1",
        "grade": "高一",
        "role": "student",
    }
    data.update(overrides)
    return RegisterRequest(**data)


def _user(**overrides) -> User:
    data = {
        "username": "test_user_1",
        "password_hash": hash_password("test-pass-123"),
        "nickname": "测试用户_1",
        "grade": "高一",
        "role": "student",
    }
    data.update(overrides)
    user = User(**data)
    user.id = 1
    user.created_at = datetime.now(timezone.utc)
    return user


def test_register_user_normalizes_username_and_hashes_password() -> None:
    session = FakeSession()
    user = register_user(session, _payload())
    assert user.username == "test_user_1"
    assert user.password_hash != "test-pass-123"
    assert verify_password("test-pass-123", user.password_hash) is True
    assert session.commits == 1
    assert session.refreshed == [user]


def test_register_user_duplicate_raises_conflict_and_rolls_back() -> None:
    session = FakeSession(commit_error=IntegrityError("INSERT", {}, Exception("duplicate")))
    with pytest.raises(UserAlreadyExistsError) as excinfo:
        register_user(session, _payload())
    assert excinfo.value.code == 40900
    assert session.rollbacks == 1


def test_authenticate_user_returns_matching_user() -> None:
    session = FakeSession(user=_user())
    user = authenticate_user(session, username="test_user_1", password="test-pass-123")
    assert user.id == 1


def test_authenticate_user_unknown_verifies_dummy_hash(monkeypatch) -> None:
    session = FakeSession(user=None)
    verified: list[str] = []

    def fake_verify(password: str, password_hash: str) -> bool:
        verified.append(password_hash)
        return False

    monkeypatch.setattr(auth_service, "verify_password", fake_verify)
    with pytest.raises(AuthError) as excinfo:
        authenticate_user(session, username="nobody_1", password="whatever-123")
    assert verified, "用户不存在时也必须跑一次哈希校验"
    assert excinfo.value.message == "用户名或密码错误"


def test_authenticate_user_wrong_password_raises_same_message() -> None:
    session = FakeSession(user=_user())
    with pytest.raises(AuthError) as excinfo:
        authenticate_user(session, username="test_user_1", password="wrong-pass-1")
    assert excinfo.value.message == "用户名或密码错误"


def test_issue_token_for_respects_configured_expiry(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        auth_secret_key="test-secret-0123456789abcdef0123456789abcd",
        auth_access_token_expire_minutes=30,
    )
    monkeypatch.setattr(security, "get_settings", lambda: settings)
    token_out = issue_token_for(_user())
    assert token_out.expires_in == 1800
    assert token_out.token_type == "bearer"
    assert token_out.user.username == "test_user_1"
    claims = decode_access_token(token_out.access_token)
    assert claims.user_id == 1
    assert claims.role == "student"