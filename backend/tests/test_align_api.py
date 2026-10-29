"""S2-10 对齐接口：TestClient + FakeSession/依赖覆盖。"""
from __future__ import annotations

from types import SimpleNamespace
from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.note import Note
from app.models.user import User
from app.schemas.common import PageData
from app.schemas.kp_align import AlignBatchOut, PendingAlignOut
from app.services import kp_align_service
from app.tasks.queue import get_task_queue


class FakeSession:
    def __init__(self, *, user: User | None = None, note: Note | None = None) -> None:
        self.user = user
        self.note = note
        self.added: list[object] = []
        self.commits = 0

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        raise AssertionError(entity)

    def get(self, entity: type, pk: int):
        if entity is Note:
            return self.note
        raise AssertionError(entity)

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, instance: object) -> None:
        now = datetime.now(timezone.utc)
        if getattr(instance, "id", None) is None:
            instance.id = 42
        if getattr(instance, "created_at", None) is None:
            instance.created_at = now
        instance.updated_at = now


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, int]] = []

    def enqueue(self, name: str, task_id: int) -> None:
        self.enqueued.append((name, task_id))


def _user(role: str = "student", user_id: int = 1) -> User:
    user = User(
        username=f"{role}_align",
        password_hash="hash",
        nickname="测试用户_1",
        grade="高一",
        role=role,
    )
    user.id = user_id
    user.created_at = datetime.now(timezone.utc)
    return user


def _note(user_id: int = 1) -> Note:
    note = Note(
        user_id=user_id,
        subject_id=1,
        title="单调性",
        content_md="内容",
        content_text="内容",
        tags=None,
        folder=None,
    )
    note.id = 7
    note.deleted_at = None
    return note


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


def test_manual_align_returns_202_task(client: TestClient) -> None:
    user = _user()
    queue = FakeQueue()
    app.dependency_overrides[get_db] = lambda: FakeSession(user=user, note=_note())
    app.dependency_overrides[get_task_queue] = lambda: queue
    resp = client.post("/api/v1/kp/align/notes/7", headers=_headers(user))
    assert resp.status_code == 202
    assert resp.json()["data"]["name"] == "kp.align"
    assert queue.enqueued[0][0] == "kp.align"


def test_manual_align_other_note_returns_403(client: TestClient) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user=user, note=_note(user_id=2))
    resp = client.post("/api/v1/kp/align/notes/7", headers=_headers(user))
    assert resp.status_code == 403


def test_manual_align_missing_note_returns_404(client: TestClient) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user=user, note=None)
    resp = client.post("/api/v1/kp/align/notes/999", headers=_headers(user))
    assert resp.status_code == 404


def test_pending_list_returns_page(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user=user)
    monkeypatch.setattr(
        kp_align_service,
        "list_pending",
        lambda session, *, viewer, params, note_id=None: PageData(
            items=[
                PendingAlignOut(
                    note_id=3,
                    kp_id=12,
                    confidence=0.68,
                    note_title="函数单调性笔记",
                    note_excerpt="函数单调性笔记摘要",
                    kp_name="函数的单调性",
                    kp_code="MATH-FUNC-02",
                )
            ],
            total=1,
            page=1,
            page_size=20,
        ),
    )
    resp = client.get("/api/v1/kp/align/pending", headers=_headers(user))
    assert resp.status_code == 200
    assert resp.json()["data"]["items"][0]["kp_code"] == "MATH-FUNC-02"
    assert resp.json()["data"]["items"][0]["note_excerpt"] == "函数单调性笔记摘要"


def test_pending_list_filters_note_id(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user=user)
    captured: dict[str, object] = {}

    def fake_list(session, *, viewer, params, note_id=None):
        captured["note_id"] = note_id
        return PageData(items=[], total=0, page=1, page_size=20)

    monkeypatch.setattr(kp_align_service, "list_pending", fake_list)
    resp = client.get("/api/v1/kp/align/pending?note_id=9", headers=_headers(user))
    assert resp.status_code == 200
    assert captured["note_id"] == 9


def test_confirm_returns_counts(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user=user)
    monkeypatch.setattr(
        kp_align_service,
        "confirm_pairs",
        lambda session, *, viewer, pairs: AlignBatchOut(confirmed=len(pairs), skipped=0),
    )
    resp = client.post(
        "/api/v1/kp/align/confirm",
        json={"items": [{"note_id": 3, "kp_id": 12}]},
        headers=_headers(user),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["confirmed"] == 1


def test_reject_returns_counts(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user=user)
    monkeypatch.setattr(
        kp_align_service,
        "reject_pairs",
        lambda session, *, viewer, pairs: AlignBatchOut(deleted=len(pairs), skipped=0),
    )
    resp = client.post(
        "/api/v1/kp/align/reject",
        json={"items": [{"note_id": 3, "kp_id": 12}]},
        headers=_headers(user),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] == 1


def test_confirm_empty_items_returns_422(client: TestClient) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user=user)
    resp = client.post(
        "/api/v1/kp/align/confirm", json={"items": []}, headers=_headers(user)
    )
    assert resp.status_code == 422

def test_pending_align_out_truncates_note_excerpt() -> None:
    row = SimpleNamespace(
        note_id=3,
        kp_id=12,
        confidence=0.68,
        note=SimpleNamespace(
            title="函数单调性笔记",
            content_text="  " + "知" * 350 + "  ",
        ),
        knowledge_point=SimpleNamespace(name="函数的单调性", code="MATH-FUNC-02"),
    )

    out = PendingAlignOut.model_validate(row)

    assert out.note_excerpt == "知" * 300 + "…"
    assert len(out.note_excerpt) == 301


def test_pending_align_out_keeps_short_excerpt() -> None:
    row = SimpleNamespace(
        note_id=3,
        kp_id=12,
        confidence=0.68,
        note=SimpleNamespace(title="短笔记", content_text="  函数图像  "),
        knowledge_point=SimpleNamespace(name="函数", code="MATH-FUNC"),
    )

    out = PendingAlignOut.model_validate(row)

    assert out.note_excerpt == "函数图像"
