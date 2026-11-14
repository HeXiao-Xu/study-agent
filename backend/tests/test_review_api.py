"""S5-5 复习接口：5 个路由、权限、404/409、Envelope。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.main import app
from app.models.user import User
from app.schemas.review import ReviewItemOut, ReviewTodayOut
from app.services import review_service


class FakeSession:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def _user(role="student") -> User:
    return User(id=50, username="s5_5_test", password_hash="x", role=role, nickname="测试")


def _today() -> ReviewTodayOut:
    return ReviewTodayOut(
        date="2026-11-14",
        timezone="Asia/Shanghai",
        items=[],
        item_count=0,
        total_minutes=0,
        cap_minutes=35,
        truncated_count=None,
    )


def _item() -> ReviewItemOut:
    return ReviewItemOut(
        id=9,
        kp_id=117,
        kp_name="函数",
        subject_id=7,
        ref_type="question",
        ref_id=501,
        ref_title="题干",
        ref_available=True,
        due_at=datetime(2026, 11, 14, tzinfo=timezone.utc),
        interval_days=2,
        priority=0.7,
        estimated_minutes=6,
        mastery=0.2,
        mastery_t=0.2,
        stability=2.0,
        attempts=1,
        overdue_days=0.0,
        low_mastery=True,
        done_at=None,
    )


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: FakeSession()
    app.dependency_overrides[get_current_user] = lambda: _user()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_today_envelope(client, monkeypatch):
    monkeypatch.setattr(review_service, "get_today", lambda *a, **k: _today())
    response = client.get("/api/v1/review/today")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["item_count"] == 0


def test_refresh_commits(client, monkeypatch):
    session = FakeSession()
    app.dependency_overrides[get_db] = lambda: session
    monkeypatch.setattr(review_service, "refresh_user", lambda *a, **k: _today())
    response = client.post("/api/v1/review/refresh")
    assert response.status_code == 200
    assert session.commits == 1


def test_done_skip_later_return_item(client, monkeypatch):
    monkeypatch.setattr(review_service, "mark_item", lambda *a, **k: _item())
    for action in ("done", "skip", "later"):
        response = client.post(f"/api/v1/review/items/9/{action}")
        assert response.status_code == 200
        assert response.json()["data"]["id"] == 9


def test_actions_map_errors(client, monkeypatch):
    def raise_conflict(*args, **kwargs):
        raise ConflictError("该复习项已完成")

    monkeypatch.setattr(review_service, "mark_item", raise_conflict)
    assert client.post("/api/v1/review/items/9/done").status_code == 409

    def raise_missing(*args, **kwargs):
        raise NotFoundError("复习项不存在")

    monkeypatch.setattr(review_service, "mark_item", raise_missing)
    assert client.post("/api/v1/review/items/9/later").status_code == 404


def test_requires_login():
    app.dependency_overrides.clear()
    with TestClient(app) as test_client:
        assert test_client.get("/api/v1/review/today").status_code == 401


def test_forbidden_for_teacher():
    app.dependency_overrides[get_db] = lambda: FakeSession()
    app.dependency_overrides[get_current_user] = lambda: _user("teacher")
    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/review/today")
    assert response.status_code == 403
    app.dependency_overrides.clear()