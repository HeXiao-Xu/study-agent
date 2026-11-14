"""S5-6 报告接口：权限、range 校验、service 透传、错误壳。"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.v1 import reports as reports_api
from app.core.cache import MemoryCache
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


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch: pytest.MonkeyPatch) -> MemoryCache:
    """禁止接口测试写真实 Redis；需要时测试可再次覆盖 get_cache。"""
    cache = MemoryCache()
    monkeypatch.setattr(reports_api, "get_cache", lambda: cache)
    return cache


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
        assert client.get("/api/v1/reports/weekly").status_code == 401
        assert client.post("/api/v1/reports/weekly").status_code == 401


def test_reports_api_rejects_non_student() -> None:
    client = _client(_user("teacher"))
    try:
        assert client.get("/api/v1/reports/mastery").status_code == 403
        assert client.get("/api/v1/reports/weekly").status_code == 403
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


def test_weekly_get_returns_cached_report(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = object()
    seen: dict[str, object] = {}

    def fake_load(cache_arg, **kwargs):  # noqa: ANN001, ANN003, ANN202
        seen.update({"cache": cache_arg, **kwargs})
        return _weekly()

    monkeypatch.setattr(reports_api, "get_cache", lambda: cache)
    monkeypatch.setattr(report_service, "load_weekly_report", fake_load)
    client = _client(_user())
    try:
        resp = client.get("/api/v1/reports/weekly")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert seen == {"cache": cache, "user_id": 50}
        assert data["report_md"] == "本周暂无学习记录。"
    finally:
        app.dependency_overrides.clear()


def test_weekly_get_returns_null_on_cache_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reports_api, "get_cache", lambda: object())
    monkeypatch.setattr(
        report_service, "load_weekly_report", lambda cache, **kwargs: None
    )
    client = _client(_user())
    try:
        resp = client.get("/api/v1/reports/weekly")
        assert resp.status_code == 200
        assert resp.json()["data"] is None
    finally:
        app.dependency_overrides.clear()


def test_weekly_post_writes_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = object()
    captured: dict[str, object] = {}
    report = _weekly()

    monkeypatch.setattr(reports_api, "get_cache", lambda: cache)
    monkeypatch.setattr(
        report_service, "generate_weekly", lambda session, **kwargs: report
    )

    def fake_store(cache_arg, **kwargs):  # noqa: ANN001, ANN003, ANN202
        captured.update({"cache": cache_arg, **kwargs})
        return True

    monkeypatch.setattr(report_service, "store_weekly_report", fake_store)
    client = _client(_user())
    try:
        assert client.post("/api/v1/reports/weekly").status_code == 200
        assert captured == {"cache": cache, "user_id": 50, "report": report}
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