"""S4-2 错题接口：路由层只验状态码/壳结构/权限闸门/声明顺序。

业务规则（状态机、归属隔离、筛选 SQL、统计聚合）在 service 层用 FakeSession
测过，这里 monkeypatch service，避免把同一规则测两遍（与 test_questions_api.py 同口径）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.core.exceptions import NotFoundError
from app.core.storage import get_storage
from app.main import app
from app.models.subject import Subject
from app.models.user import User
from app.schemas.common import PageData
from app.schemas.mistake import (
    CauseCountOut,
    KpCountOut,
    MistakeDetailOut,
    MistakeStatsOut,
    MistakeSummaryOut,
    StatusCountOut,
)
from app.services import mistake_service
from app.tasks.queue import get_task_queue


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, int]] = []

    def enqueue(self, name: str, task_id: int) -> None:  # pragma: no cover - 路由测试不入队
        self.enqueued.append((name, task_id))


class FakeStorage:
    def download_to(self, key, handle) -> None:  # pragma: no cover - 路由测试不下载
        raise AssertionError("路由测试不应触发下载")


class FakeSession:
    def __init__(self, *, subject: Subject | None = None) -> None:
        self.subject = subject

    def get(self, entity, pk):
        if entity is Subject:
            return self.subject
        return None


def _user(role: str = "student", user_id: int = 1) -> User:
    user = User(username=f"{role}_api", password_hash="hash", nickname="测试用户_1",
                grade="高一", role=role)
    user.id = user_id
    return user


def _now() -> datetime:
    return datetime(2026, 11, 3, tzinfo=timezone.utc)


def _detail(mistake_id: int = 1) -> MistakeDetailOut:
    return MistakeDetailOut(
        id=mistake_id,
        question_id=11,
        status="待订正",
        correct_streak=0,
        stem_excerpt="已知函数 f(x)=x²",
        subject_id=7,
        qtype="解答",
        difficulty=2,
        created_at=_now(),
        stem_md="已知函数 f(x)=x²，求 f(1)。",
    )


def _summary(mistake_id: int = 1) -> MistakeSummaryOut:
    return MistakeSummaryOut(
        id=mistake_id,
        question_id=11,
        status="待订正",
        correct_streak=0,
        stem_excerpt="已知函数 f(x)=x²",
        subject_id=7,
        qtype="解答",
        difficulty=2,
        created_at=_now(),
    )


def _stats() -> MistakeStatsOut:
    return MistakeStatsOut(
        total=1,
        by_status=[StatusCountOut(status="待订正", count=1)],
        by_cause=[CauseCountOut(cause_type="概念不清", count=1)],
        top_kps=[KpCountOut(kp_id=3, kp_name="函数的单调性", count=1)],
    )


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


def _client(*, session=None, user=None, role: str = "student") -> TestClient:
    app.dependency_overrides[get_db] = lambda: session or FakeSession()
    app.dependency_overrides[get_current_user] = lambda: user or _user(role=role)
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_task_queue] = lambda: FakeQueue()
    return TestClient(app)


# --------------------------------------------------------------------------
# 声明顺序：/photo 与 /stats 必须先于 /{mistake_id}
# --------------------------------------------------------------------------
def test_photo_and_stats_routes_declared_before_path_param() -> None:
    from app.api.v1.mistakes import router

    paths = [route.path for route in router.routes]
    assert paths.index("/mistakes/photo") < paths.index("/mistakes/{mistake_id}")
    assert paths.index("/mistakes/stats") < paths.index("/mistakes/{mistake_id}")


# --------------------------------------------------------------------------
# 权限闸门：8 条路由全部先过认证，未带 Bearer 一律 401（包括 /photo 带文件）
# --------------------------------------------------------------------------
_AUTH_CASES = [
    ("get", "/api/v1/mistakes", {}),
    ("post", "/api/v1/mistakes", {"json": {"question_id": 1}}),
    ("get", "/api/v1/mistakes/1", {}),
    ("patch", "/api/v1/mistakes/1", {"json": {"my_answer_md": "待订正"}}),
    ("post", "/api/v1/mistakes/1/review", {"json": {"correct": True}}),
    ("delete", "/api/v1/mistakes/1", {}),
    (
        "post",
        "/api/v1/mistakes/photo",
        {
            "files": {"file": ("shot.png", b"\x89PNG\r\n\x1a\n" + b"0" * 8, "image/png")},
            "params": {"subject_id": 7},
        },
    ),
    ("get", "/api/v1/mistakes/stats", {}),
]


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    _AUTH_CASES,
    ids=["list", "create", "detail", "update", "review", "delete", "photo", "stats"],
)
def test_every_route_requires_auth(method, path, kwargs) -> None:
    # 只覆盖 get_db、不覆盖 get_current_user：无 Bearer 时由 get_current_user 拦下。
    app.dependency_overrides[get_db] = lambda: FakeSession()
    response = TestClient(app).request(method, path, **kwargs)
    assert response.status_code == 401
    assert response.json()["code"] == 40100


# --------------------------------------------------------------------------
# POST /mistakes —— 题库录入
# --------------------------------------------------------------------------
def test_create_from_question_returns_201(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_create(session, *, user_id, payload):
        captured["user_id"] = user_id
        captured["question_id"] = payload.question_id
        return _detail(11), True

    monkeypatch.setattr(mistake_service, "create_from_question", fake_create)
    response = _client(user=_user(user_id=42)).post(
        "/api/v1/mistakes", json={"question_id": 11}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["created"] is True
    assert body["data"]["id"] == 11
    assert captured == {"user_id": 42, "question_id": 11}


def test_create_duplicate_returns_201_with_created_false(monkeypatch) -> None:
    """同题重复录入是复用语义（spec D-1）：契约允许 201，不能退化成 409。"""
    results = iter([(_detail(11), True), (_detail(11), False)])
    monkeypatch.setattr(
        mistake_service, "create_from_question", lambda *args, **kwargs: next(results)
    )
    client = _client()
    first = client.post("/api/v1/mistakes", json={"question_id": 11})
    second = client.post("/api/v1/mistakes", json={"question_id": 11})
    assert first.status_code == 201
    assert first.json()["data"]["created"] is True
    assert second.status_code == 201
    assert second.json()["data"]["created"] is False


# --------------------------------------------------------------------------
# POST /mistakes/photo —— 拍照录入（含 R1-b 手填作答透传）
# --------------------------------------------------------------------------
def test_photo_rejects_non_image() -> None:
    client = _client(session=FakeSession(subject=Subject(name="数学")))
    response = client.post(
        "/api/v1/mistakes/photo",
        files={"file": ("a.txt", b"hello", "text/plain")},
        params={"subject_id": 7},
    )
    assert response.status_code == 422
    assert response.json()["code"] == 42200


@pytest.mark.parametrize("my_answer_md", ["选 B，因为 f(1)=0", None])
def test_photo_passes_my_answer_md_to_service(monkeypatch, my_answer_md) -> None:
    captured: dict[str, object] = {}

    def fake_start(session, *, owner, subject_id, upload, storage, queue, my_answer_md=None):
        captured["my_answer_md"] = my_answer_md
        captured["filename"] = upload.filename
        captured["subject_id"] = subject_id
        return SimpleNamespace(
            id=5, name="mistake.recognize", status="pending", created_at=_now()
        )

    monkeypatch.setattr(mistake_service, "start_photo_recognize", fake_start)
    response = _client().post(
        "/api/v1/mistakes/photo",
        files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n" + b"0" * 8, "image/png")},
        params={"subject_id": 7},
        data={} if my_answer_md is None else {"my_answer_md": my_answer_md},
    )
    assert response.status_code == 202
    assert response.json()["data"]["name"] == "mistake.recognize"
    assert captured["my_answer_md"] == my_answer_md
    assert captured["filename"] == "shot.png"
    assert captured["subject_id"] == 7


# --------------------------------------------------------------------------
# GET /mistakes —— 列表
# --------------------------------------------------------------------------
def test_list_rejects_invalid_status(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("非法 status 不应进 service")

    monkeypatch.setattr(mistake_service, "list_mistakes", boom)
    response = _client().get("/api/v1/mistakes", params={"status": "已作废"})
    assert response.status_code == 422
    assert response.json()["code"] == 42200


def test_list_passes_filters_and_user_to_service(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_list(session, *, user_id, filters, page, sort):
        captured["user_id"] = user_id
        captured["filters"] = filters
        captured["page"] = page
        captured["sort"] = sort
        return PageData(items=[_summary()], total=1, page=page.page, page_size=page.page_size)

    monkeypatch.setattr(mistake_service, "list_mistakes", fake_list)
    response = _client(user=_user(user_id=42)).get(
        "/api/v1/mistakes",
        params={"status": "待订正", "cause_type": "概念不清", "kp_id": 3,
                "created_from": "2026-01-01T00:00:00+00:00",
                "created_to": "2026-06-01T00:00:00+00:00",
                "page": 2, "page_size": 5, "sort_by": "status", "order": "asc"},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["data"]["total"] == 1
    assert body["data"]["page"] == 2
    assert body["data"]["page_size"] == 5
    assert body["data"]["items"][0]["status"] == "待订正"
    assert captured["user_id"] == 42
    filters = captured["filters"]
    assert filters.status == "待订正"
    assert filters.cause_type == "概念不清"
    assert filters.kp_id == 3
    assert filters.created_from == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert filters.created_to == datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert captured["sort"].sort_by == "status"
    assert captured["sort"].order == "asc"


# --------------------------------------------------------------------------
# GET /mistakes/stats —— 统计
# --------------------------------------------------------------------------
def test_stats_returns_four_fields(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_stats(session, *, user_id, created_from=None, created_to=None):
        captured["user_id"] = user_id
        return _stats()

    monkeypatch.setattr(mistake_service, "stats", fake_stats)
    response = _client(user=_user(user_id=42)).get("/api/v1/mistakes/stats")
    assert response.status_code == 200
    body = response.json()
    assert set(body["data"]) == {"total", "by_status", "by_cause", "top_kps"}
    assert captured["user_id"] == 42


# --------------------------------------------------------------------------
# GET/PATCH/DELETE /mistakes/{id}
# --------------------------------------------------------------------------
def test_detail_returns_envelope(monkeypatch) -> None:
    monkeypatch.setattr(
        mistake_service, "get_detail", lambda *args, **kwargs: _detail(3)
    )
    response = _client().get("/api/v1/mistakes/3")
    assert response.status_code == 200
    assert response.json()["data"]["id"] == 3


def test_detail_not_found_returns_404(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise NotFoundError("错题不存在")

    monkeypatch.setattr(mistake_service, "get_detail", boom)
    response = _client().get("/api/v1/mistakes/999")
    assert response.status_code == 404
    assert response.json()["code"] == 40400


def test_patch_rejects_null_status() -> None:
    response = _client().patch("/api/v1/mistakes/1", json={"status": None})
    assert response.status_code == 422
    assert response.json()["code"] == 42200


def test_patch_rejects_invalid_status_value() -> None:
    response = _client().patch("/api/v1/mistakes/1", json={"status": "已通关"})
    assert response.status_code == 422
    assert response.json()["code"] == 42200


# --------------------------------------------------------------------------
# POST /mistakes/{id}/review —— 复习记录
# --------------------------------------------------------------------------
def test_review_requires_correct_field() -> None:
    response = _client().post("/api/v1/mistakes/1/review", json={})
    assert response.status_code == 422


def test_review_passes_correct_to_service(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_review(session, *, user_id, mistake_id, correct):
        captured["user_id"] = user_id
        captured["mistake_id"] = mistake_id
        captured["correct"] = correct
        return _detail(mistake_id)

    monkeypatch.setattr(mistake_service, "record_review", fake_review)
    response = _client(user=_user(user_id=42)).post(
        "/api/v1/mistakes/9/review", json={"correct": True}
    )
    assert response.status_code == 200
    assert response.json()["data"]["id"] == 9
    assert captured == {"user_id": 42, "mistake_id": 9, "correct": True}


# --------------------------------------------------------------------------
# DELETE /mistakes/{id} —— 204 且无响应体
# --------------------------------------------------------------------------
def test_delete_returns_204_without_body(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_delete(session, *, user_id, mistake_id):
        captured["user_id"] = user_id
        captured["mistake_id"] = mistake_id

    monkeypatch.setattr(mistake_service, "delete_mistake", fake_delete)
    response = _client(user=_user(user_id=42)).delete("/api/v1/mistakes/7")
    assert response.status_code == 204
    assert response.content == b""
    assert captured == {"user_id": 42, "mistake_id": 7}


@pytest.mark.parametrize(
    "mistake_id", [999, 7], ids=["not-found", "other-owner"]
)
def test_delete_missing_or_foreign_returns_404(monkeypatch, mistake_id) -> None:
    """不存在与他人错题在 service 统一成 NotFoundError，路由不能变 500。"""

    def boom(*args, **kwargs):
        raise NotFoundError("错题不存在")

    monkeypatch.setattr(mistake_service, "delete_mistake", boom)
    response = _client(user=_user(user_id=42)).delete(f"/api/v1/mistakes/{mistake_id}")
    assert response.status_code == 404
    assert response.json()["code"] == 40400
