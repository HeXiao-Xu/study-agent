"""S2-2 认证接口测试：TestClient + get_db 依赖覆盖，不连真实数据库（spec §9.3）。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.user import User

REGISTER_BODY = {
    "username": "Test_User_1",
    "password": "test-pass-123",
    "nickname": "测试用户_1",
    "grade": "高一",
    "role": "student",
}


class FakeSession:
    def __init__(self, *, user: User | None = None, commit_error: Exception | None = None) -> None:
        self.user = user
        self.commit_error = commit_error
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, instance: object) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = 1
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)

    def scalar(self, statement: object) -> User | None:
        return self.user


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


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _override(session: FakeSession) -> None:
    app.dependency_overrides[get_db] = lambda: session


def test_register_returns_201_envelope_without_password_hash(client: TestClient) -> None:
    _override(FakeSession())
    resp = client.post("/api/v1/auth/register", json=REGISTER_BODY)
    assert resp.status_code == 201
    body = resp.json()
    assert body["code"] == 0
    assert body["trace_id"]
    assert body["data"]["username"] == "test_user_1"
    assert body["data"]["role"] == "student"
    assert "password_hash" not in body["data"]


def test_register_rejects_short_password(client: TestClient) -> None:
    _override(FakeSession())
    resp = client.post(
        "/api/v1/auth/register", json={**REGISTER_BODY, "password": "short"}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_register_rejects_admin_role(client: TestClient) -> None:
    _override(FakeSession())
    resp = client.post(
        "/api/v1/auth/register", json={**REGISTER_BODY, "role": "admin"}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_register_rejects_username_with_space(client: TestClient) -> None:
    _override(FakeSession())
    resp = client.post(
        "/api/v1/auth/register", json={**REGISTER_BODY, "username": "bad user"}
    )
    assert resp.status_code == 422


def test_register_duplicate_username_returns_409(client: TestClient) -> None:
    _override(FakeSession(commit_error=IntegrityError("INSERT", {}, Exception("dup"))))
    resp = client.post("/api/v1/auth/register", json=REGISTER_BODY)
    assert resp.status_code == 409
    assert resp.json()["code"] == 40900
    assert resp.json()["message"] == "用户名已存在"


def test_login_returns_token_envelope(client: TestClient) -> None:
    _override(FakeSession(user=_user()))
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "Test_User_1", "password": "test-pass-123"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["access_token"]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0
    assert data["user"]["id"] == 1


def test_login_wrong_password_and_unknown_user_share_message(client: TestClient) -> None:
    _override(FakeSession(user=_user()))
    wrong = client.post(
        "/api/v1/auth/login",
        json={"username": "test_user_1", "password": "wrong-pass-1"},
    )
    _override(FakeSession(user=None))
    unknown = client.post(
        "/api/v1/auth/login",
        json={"username": "nobody_1", "password": "wrong-pass-1"},
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["message"] == unknown.json()["message"] == "用户名或密码错误"
    assert wrong.json()["code"] == unknown.json()["code"] == 40100


def test_me_without_token_returns_401(client: TestClient) -> None:
    _override(FakeSession(user=_user()))
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["message"] == "未提供认证凭据"


def test_me_with_valid_token_returns_user(client: TestClient) -> None:
    _override(FakeSession(user=_user()))
    token = create_access_token(user_id=1, role="student").token
    resp = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["username"] == "test_user_1"


def test_me_with_expired_token_returns_401(client: TestClient) -> None:
    _override(FakeSession(user=_user()))
    token = create_access_token(
        user_id=1, role="student", expires_delta=timedelta(seconds=-5)
    ).token
    resp = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401
    assert "过期" in resp.json()["message"]


def test_me_with_garbage_token_returns_401(client: TestClient) -> None:
    _override(FakeSession(user=_user()))
    resp = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert resp.status_code == 401
    assert resp.json()["message"] == "无效的认证凭据"