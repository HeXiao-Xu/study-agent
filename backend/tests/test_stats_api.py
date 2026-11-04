"""S4-8 统计接口：权限、参数校验、透传与出参字段名。"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.schemas.stats import StatsOverviewOut, StatsRangeOut, StatsSummaryOut
from app.services import stats_service


def _user(role: str = "student") -> User:
    user = User(
        username=f"{role}_s48", nickname=role, grade="高二", role=role, password_hash="x"
    )
    user.id = 50 if role == "student" else 9
    return user


def _client(user: User):  # noqa: ANN202
    class _Session:
        def get(self, model, pk):  # noqa: ANN001, ANN201
            return user if model is User else None

        def scalar(self, statement):  # noqa: ANN001, ANN201
            return user if "users" in str(statement) else None

        def flush(self) -> None:
            return None

    app.dependency_overrides[get_db] = lambda: _Session()
    client = TestClient(app)
    token = create_access_token(user_id=user.id, role=user.role).token
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _empty_overview(range_key: str, start: date, end: date) -> StatsOverviewOut:
    return StatsOverviewOut(
        range=StatsRangeOut(key=range_key, from_=start, to=end),
        summary=StatsSummaryOut(
            total=0,
            pending=0,
            corrected=0,
            mastered=0,
            analyzed=0,
            with_kp=0,
            mastery_rows=0,
        ),
        by_status=[],
        by_cause=[],
        top_kps=[],
        trend=[],
    )


def test_stats_api_requires_auth() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/stats/overview").status_code == 401


def test_stats_api_rejects_non_student() -> None:
    client = _client(_user("teacher"))
    try:
        assert client.get("/api/v1/stats/overview").status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_stats_api_rejects_unknown_range() -> None:
    client = _client(_user())
    try:
        resp = client.get("/api/v1/stats/overview?range=365d")
        assert resp.status_code == 422
        assert resp.json()["code"] == 42200
    finally:
        app.dependency_overrides.clear()


def test_stats_api_forwards_range_and_user(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_overview(session, **kwargs):  # noqa: ANN001, ANN003, ANN202
        captured.update(kwargs)
        return _empty_overview("7d", date(2026, 10, 29), date(2026, 11, 4))

    monkeypatch.setattr(stats_service, "overview", fake_overview)
    client = _client(_user())
    try:
        resp = client.get("/api/v1/stats/overview?range=7d")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert captured == {"user_id": 50, "range_key": "7d"}
        assert data["range"]["from"] == "2026-10-29"
        assert data["range"]["key"] == "7d"
    finally:
        app.dependency_overrides.clear()


def test_stats_api_defaults_to_30d(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_overview(session, **kwargs):  # noqa: ANN001, ANN003, ANN202
        captured.update(kwargs)
        return _empty_overview("30d", date(2026, 10, 6), date(2026, 11, 4))

    monkeypatch.setattr(stats_service, "overview", fake_overview)
    client = _client(_user())
    try:
        assert client.get("/api/v1/stats/overview").status_code == 200
        assert captured["range_key"] == "30d"
    finally:
        app.dependency_overrides.clear()