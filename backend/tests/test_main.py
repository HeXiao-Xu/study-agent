"""S0-5 冒烟测试：/health、统一错误壳、X-Trace-Id 透出（无外部依赖）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_unified_envelope() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["message"] == "ok"
    assert body["trace_id"]
    assert body["data"]["status"] == "ok"
    assert body["data"]["app"] == "study-agent"


def test_unknown_route_returns_unified_error() -> None:
    resp = client.get("/definitely-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == 40400
    assert body["data"] is None
    assert body["message"]
    # 错误体里的 trace_id 与响应头一致（契约：trace_id 透出格式）
    assert resp.headers["x-trace-id"] == body["trace_id"]


def test_trace_id_echo_from_request_header() -> None:
    resp = client.get("/health", headers={"X-Trace-Id": "trace-abc-123"})
    assert resp.headers["x-trace-id"] == "trace-abc-123"
    assert resp.json()["trace_id"] == "trace-abc-123"
