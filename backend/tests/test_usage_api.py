"""S3-7 管理端用量接口：鉴权、range 校验与响应壳。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1 import admin as admin_module
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.schemas.usage import UsageItem, UsageReport, UsageTotals


class FakeSession:
    def __init__(self, user: User | None) -> None:
        self.user = user

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        raise AssertionError(f"unexpected entity: {entity}")


def _user(role: str = "admin") -> User:
    user = User(
        username=f"{role}_1",
        password_hash="hash",
        nickname="测试用户",
        grade=None,
        role=role,
    )
    user.id = 1
    user.created_at = datetime.now(timezone.utc)
    return user


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_usage_requires_token(client: TestClient) -> None:
    app.dependency_overrides[deps.get_db] = lambda: FakeSession(None)
    resp = client.get("/api/v1/admin/usage?range=7d")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_usage_rejects_non_admin_and_bad_range(client: TestClient) -> None:
    student = _user("student")
    app.dependency_overrides[deps.get_db] = lambda: FakeSession(student)
    resp = client.get("/api/v1/admin/usage?range=7d", headers=_headers(student))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300

    admin = _user("admin")
    app.dependency_overrides[deps.get_db] = lambda: FakeSession(admin)
    resp = client.get("/api/v1/admin/usage?range=999d", headers=_headers(admin))
    assert resp.status_code == 422


def test_usage_returns_report(client: TestClient, monkeypatch) -> None:
    admin = _user("admin")
    app.dependency_overrides[deps.get_db] = lambda: FakeSession(admin)
    report = UsageReport(
        range="7d",
        start_date=date(2026, 10, 26),
        end_date=date(2026, 11, 1),
        totals=UsageTotals(calls=2, total_tokens=120, cost_yuan=0.0002),
        items=[
            UsageItem(
                date=date(2026, 11, 1),
                scene="qa",
                model="qwen-plus",
                calls=2,
                total_tokens=120,
                cost_yuan=0.0002,
                avg_latency_ms=100,
            )
        ],
    )
    monkeypatch.setattr(
        admin_module.usage_service, "get_usage", lambda session, *, range_key: report
    )
    resp = client.get("/api/v1/admin/usage?range=7d", headers=_headers(admin))
    body = resp.json()
    assert resp.status_code == 200
    assert body["code"] == 0
    assert body["data"]["range"] == "7d"
    assert body["data"]["items"][0]["scene"] == "qa"
    assert body["data"]["totals"]["calls"] == 2