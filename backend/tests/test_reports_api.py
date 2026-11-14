"""S5-6 报告接口：权限、range 校验、service 透传、错误壳。"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.schemas.report import (
    NumberValidationOut,
    ReportOverviewOut,
    ReportRangeOut,
    WeeklyMasteryOut,
    WeeklyPeriodOut,
    WeeklyReportOut,
    WeeklyStatsOut,
    WeeklyTotalsOut,
)
from app.services import report_service


def _user(role: str = "student") -> User:
    user = User(
        username=f"{role}_s56", nickname=role, grade="高二", role=role, password_hash="x"
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


def _empty_overview() -> ReportOverviewOut:
    return ReportOverviewOut(
        range=ReportRangeOut(
            key="30d", from_=date(2026, 10, 16), to=date(2026, 11, 14)
        ),
        subjects=[],
        trend=[],
    )


def _weekly() -> WeeklyReportOut:
    stats = WeeklyStatsOut(
        totals=WeeklyTotalsOut(
            new_notes=0,
            reviews_done=0,
            new_mistakes=0,
            mastered_mistakes=0,
            mistakes_net=0,
        ),
        active_days=0,
        mastery=WeeklyMasteryOut(
            assessed_kp_count=0,
            avg_mastery=None,
            weak_modules=[],
            weak_kps=[],
        ),
        trend=[],
    )
    return WeeklyReportOut(
        period=WeeklyPeriodOut(
            from_=date(2026, 11, 8), to=date(2026, 11, 14), days=7
        ),
        generated_by="empty",
        report_md="本周暂无学习记录。",
        stats=stats,
        validation=NumberValidationOut(
            ok=True, attempts=0, checked_numbers=[], invalid_numbers=[]
        ),
    )


def test_reports_api_requires_auth() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/reports/mastery").status_code == 401
        assert client.post("/api/v1/reports/weekly").status_code == 401


def test_reports_api_rejects_non_student() -> None:
    client = _client(_user("teacher"))
    try:
        assert client.get("/api/v1/reports/mastery").status_code == 403
        assert client.post("/api/v1/reports/weekly").status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_reports_api_rejects_unknown_range() -> None:
    client = _client(_user())
    try:
        resp = client.get("/api/v1/reports/mastery?range=365d")
        assert resp.status_code == 422
        assert resp.json()["code"] == 42200
    finally:
        app.dependency_overrides.clear()


def test_mastery_forwards_range_and_user(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_overview(session, **kwargs):  # noqa: ANN001, ANN003, ANN202
        captured.update(kwargs)
        return _empty_overview()

    monkeypatch.setattr(report_service, "get_overview", fake_overview)
    client = _client(_user())
    try:
        resp = client.get("/api/v1/reports/mastery?range=7d")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert captured == {"user_id": 50, "range_key": "7d"}
        assert data["range"]["from"] == "2026-10-16"
    finally:
        app.dependency_overrides.clear()


def test_mastery_defaults_to_30d(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_overview(session, **kwargs):  # noqa: ANN001, ANN003, ANN202
        captured.update(kwargs)
        return _empty_overview()

    monkeypatch.setattr(report_service, "get_overview", fake_overview)
    client = _client(_user())
    try:
        assert client.get("/api/v1/reports/mastery").status_code == 200
        assert captured["range_key"] == "30d"
    finally:
        app.dependency_overrides.clear()


def test_weekly_returns_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_generate(session, **kwargs):  # noqa: ANN001, ANN003, ANN202
        captured.update(kwargs)
        return _weekly()

    monkeypatch.setattr(report_service, "generate_weekly", fake_generate)
    client = _client(_user())
    try:
        resp = client.post("/api/v1/reports/weekly")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert captured == {"user_id": 50}
        assert data["generated_by"] == "empty"
        assert data["validation"]["ok"] is True
    finally:
        app.dependency_overrides.clear()


def test_weekly_generation_error_returns_500(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_generate(session, **kwargs):  # noqa: ANN001, ANN003, ANN202
        raise report_service.ReportGenerationError()

    monkeypatch.setattr(report_service, "generate_weekly", fake_generate)
    client = _client(_user())
    try:
        resp = client.post("/api/v1/reports/weekly")
        assert resp.status_code == 500
        assert resp.json()["code"] == 50000
        assert resp.json()["message"] == "周报生成失败"
    finally:
        app.dependency_overrides.clear()