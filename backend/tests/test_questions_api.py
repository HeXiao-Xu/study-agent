"""S4-1 题库接口：路由层只验状态码/壳结构/权限闸门。

业务规则（判重、阈值、引用保护）在 service 层用 FakeSession 测过，
这里只 monkeypatch service，避免把同一规则测两遍。
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.core.exceptions import ConflictError, ForbiddenError, InvalidParamError
from app.core.storage import get_storage
from app.main import app
from app.models.subject import Subject
from app.models.user import User
from app.schemas.common import PageData
from app.schemas.question import KpRefOut, QuestionDetailOut, QuestionSummaryOut
from app.services import file_service, question_service, task_service
from app.tasks.queue import get_task_queue


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, int]] = []

    def enqueue(self, name: str, task_id: int) -> None:
        self.enqueued.append((name, task_id))


class FakeStorage:
    def download_to(self, key, handle) -> None:  # pragma: no cover - 路由测试不下载
        raise AssertionError("路由测试不应触发下载")


class FakeSession:
    def __init__(self, *, subject: Subject | None = None) -> None:
        self.subject = subject
        self.added: list[object] = []
        self.commits = 0

    def get(self, entity, pk):
        if entity is Subject:
            return self.subject
        return None

    def add(self, instance) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1


def _user(role: str = "student", user_id: int = 1) -> User:
    user = User(username=f"{role}_api", password_hash="hash", nickname="测试用户_1",
                grade="高一", role=role)
    user.id = user_id
    return user


def _summary(question_id: int = 1) -> QuestionSummaryOut:
    return QuestionSummaryOut(
        id=question_id, subject_id=1, qtype="单选", difficulty=2, origin="upload",
        verified=True, stem_md="已知函数 f(x)=x²，求 f(1)。",
        created_at=datetime.now(timezone.utc), kp_names=["函数的单调性"],
    )


def _detail(question_id: int = 1) -> QuestionDetailOut:
    return QuestionDetailOut(
        **_summary(question_id).model_dump(),
        options_json=[{"key": "A", "text": "1"}],
        answer_md="A",
        kps=[KpRefOut(kp_id=3, kp_name="函数的单调性", kp_code="kp.3")],
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


def test_import_returns_202_and_enqueues_extract(monkeypatch) -> None:
    record = SimpleNamespace(id=9, filename="试卷.pdf")
    monkeypatch.setattr(file_service, "upload_file", lambda *args, **kwargs: (record, False))
    task = SimpleNamespace(id=5, name="question.extract", status="pending",
                           created_at=datetime.now(timezone.utc))
    monkeypatch.setattr(task_service, "create_task", lambda *args, **kwargs: task)
    client = _client(session=FakeSession(subject=Subject(name="数学")))
    response = client.post(
        "/api/v1/questions/import?subject_id=1",
        files={"file": ("试卷.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 202
    assert response.json()["data"]["name"] == "question.extract"


def test_import_student_cannot_use_exam_origin() -> None:
    client = _client(role="student")
    response = client.post(
        "/api/v1/questions/import?subject_id=1&origin=exam",
        files={"file": ("试卷.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 403
    assert response.json()["code"] == 40300


def test_list_returns_page_shell(monkeypatch) -> None:
    monkeypatch.setattr(
        question_service, "list_questions",
        lambda *args, **kwargs: PageData(items=[_summary()], total=1, page=1, page_size=20),
    )
    response = _client().get("/api/v1/questions")
    body = response.json()
    assert response.status_code == 200
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["kp_names"] == ["函数的单调性"]


def test_list_mine_filters_by_current_user(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_list(session, *, filters, page, sort):
        captured["created_by"] = filters.created_by
        return PageData(items=[], total=0, page=1, page_size=20)

    monkeypatch.setattr(question_service, "list_questions", fake_list)
    _client(user=_user(user_id=42)).get("/api/v1/questions?mine=true")
    assert captured["created_by"] == 42


def test_detail_includes_kps(monkeypatch) -> None:
    monkeypatch.setattr(question_service, "get_question_detail", lambda *a, **k: _detail())
    response = _client().get("/api/v1/questions/1")
    assert response.status_code == 200
    assert response.json()["data"]["kps"][0]["kp_name"] == "函数的单调性"


def test_create_returns_201(monkeypatch) -> None:
    monkeypatch.setattr(
        question_service, "create_question", lambda *a, **k: SimpleNamespace(id=11)
    )
    monkeypatch.setattr(question_service, "get_question_detail", lambda *a, **k: _detail(11))
    response = _client().post(
        "/api/v1/questions",
        json={"subject_id": 1, "stem_md": "已知函数 f(x)=x²，求 f(1)。", "qtype": "解答", "difficulty": 2},
    )
    assert response.status_code == 201
    assert response.json()["data"]["id"] == 11


def test_create_duplicate_returns_409(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise ConflictError("题目已存在")

    monkeypatch.setattr(question_service, "create_question", boom)
    response = _client().post(
        "/api/v1/questions",
        json={"subject_id": 1, "stem_md": "已知函数 f(x)=x²，求 f(1)。", "qtype": "解答", "difficulty": 2},
    )
    assert response.status_code == 409
    assert response.json()["code"] == 40900


def test_update_other_student_question_returns_403(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise ForbiddenError("只能修改自己创建的题目")

    monkeypatch.setattr(question_service, "update_question", boom)
    response = _client().patch("/api/v1/questions/1", json={"difficulty": 4})
    assert response.status_code == 403


def test_merge_cross_subject_returns_400(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise InvalidParamError("只能合并同一学科的题目")

    monkeypatch.setattr(question_service, "merge_questions", boom)
    response = _client(role="teacher").post("/api/v1/questions/merge", json={"ids": [1, 2]})
    assert response.status_code == 422
    assert response.json()["code"] == 42200


def test_delete_referenced_returns_409(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise ConflictError("题目已被错题本引用")

    monkeypatch.setattr(question_service, "delete_question", boom)
    response = _client().delete("/api/v1/questions/1")
    assert response.status_code == 409