"""S2-5 笔记接口测试（spec §8.3）：TestClient + get_db 覆盖，不连库。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.note import Note
from app.models.subject import Subject
from app.models.user import User
from app.models.user_relation import UserRelation
from app.schemas.common import PageData
from app.schemas.notes import NoteSummary
from app.services import note_service


class FakeSession:
    def __init__(
        self,
        *,
        user: User | None = None,
        note: Note | None = None,
        relation: int | None = None,
        subject: Subject | None = None,
    ) -> None:
        self.user = user
        self.note = note
        self.relation = relation
        self.subject = subject
        self.added: list[object] = []
        self.commits = 0

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        if entity is Note:
            return self.note
        if entity is UserRelation:
            return self.relation
        raise AssertionError(f"unexpected entity: {entity}")

    def get(self, entity: type, pk: int):
        if entity is Subject:
            return self.subject
        raise AssertionError(f"unexpected get: {entity}")

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def refresh(self, instance: object) -> None:
        now = datetime.now(timezone.utc)
        if getattr(instance, "id", None) is None:
            instance.id = 42
        if getattr(instance, "created_at", None) is None:
            instance.created_at = now
        instance.updated_at = now


def _user(
    user_id: int = 1, *, role: str = "student", username: str = "student_a"
) -> User:
    user = User(
        username=username,
        password_hash="hash",
        nickname=f"测试用户_{user_id}",
        grade="高一",
        role=role,
    )
    user.id = user_id
    user.created_at = datetime.now(timezone.utc)
    return user


def _note(note_id: int = 1, *, owner_id: int = 1) -> Note:
    now = datetime.now(timezone.utc)
    note = Note(
        user_id=owner_id,
        subject_id=None,
        title="函数单调性",
        content_md="正文 $x$",
        content_text="正文",
        tags=["函数"],
        folder=None,
        source_file_id=None,
    )
    note.id = note_id
    note.created_at = now
    note.updated_at = now
    note.deleted_at = None
    return note


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _override(session: FakeSession) -> None:
    app.dependency_overrides[get_db] = lambda: session


def test_create_note_returns_201(client: TestClient) -> None:
    session = FakeSession(user=_user())
    _override(session)
    resp = client.post(
        "/api/v1/notes",
        json={"title": "函数单调性", "content_md": "设 $x$ 递增", "tags": ["函数"]},
        headers=_headers(session.user),
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["id"] == 42
    assert data["title"] == "函数单调性"
    assert "content_text" not in data
    assert "deleted_at" not in data
    assert session.added[0].content_text == "设 递增"


def test_create_note_rejects_blank_title(client: TestClient) -> None:
    _override(FakeSession(user=_user()))
    resp = client.post(
        "/api/v1/notes",
        json={"title": "   ", "content_md": "正文"},
        headers=_headers(_user()),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_create_note_forbidden_for_teacher(client: TestClient) -> None:
    session = FakeSession(user=_user(role="teacher", username="teacher_1"))
    _override(session)
    resp = client.post(
        "/api/v1/notes",
        json={"title": "函数", "content_md": "正文"},
        headers=_headers(session.user),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_create_note_rejects_missing_subject(client: TestClient) -> None:
    session = FakeSession(user=_user(), subject=None)
    _override(session)
    resp = client.post(
        "/api/v1/notes",
        json={"title": "函数", "content_md": "正文", "subject_id": 9},
        headers=_headers(session.user),
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == "学科不存在"


def test_list_notes_returns_page_envelope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    note = _note()
    session = FakeSession(user=_user(), note=note)
    _override(session)

    def fake_paginate(session_, stmt, params, *, item_model):
        return PageData(
            items=[NoteSummary.model_validate(note)],
            total=1,
            page=params.page,
            page_size=params.page_size,
        )

    monkeypatch.setattr(note_service, "paginate_query", fake_paginate)
    resp = client.get("/api/v1/notes", headers=_headers(session.user))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) == {"items", "total", "page", "page_size"}
    assert data["items"][0]["title"] == "函数单调性"
    assert "content_md" not in data["items"][0]


def test_list_notes_rejects_unknown_sort(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = FakeSession(user=_user())
    _override(session)
    monkeypatch.setattr(note_service, "paginate_query", lambda *a, **k: None)
    resp = client.get("/api/v1/notes?sort_by=content_md", headers=_headers(session.user))
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_get_own_note_returns_detail(client: TestClient) -> None:
    session = FakeSession(user=_user(), note=_note())
    _override(session)
    resp = client.get("/api/v1/notes/1", headers=_headers(session.user))
    assert resp.status_code == 200
    assert resp.json()["data"]["content_md"] == "正文 $x$"


def test_get_other_student_note_returns_403(client: TestClient) -> None:
    session = FakeSession(user=_user(2, username="student_b"), note=_note(owner_id=1))
    _override(session)
    resp = client.get("/api/v1/notes/1", headers=_headers(session.user))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_get_note_allowed_for_bound_parent(client: TestClient) -> None:
    parent = _user(3, role="parent", username="parent_1")
    session = FakeSession(user=parent, note=_note(owner_id=1), relation=10)
    _override(session)
    resp = client.get("/api/v1/notes/1", headers=_headers(parent))
    assert resp.status_code == 200


def test_get_missing_note_returns_404(client: TestClient) -> None:
    session = FakeSession(user=_user(), note=None)
    _override(session)
    resp = client.get("/api/v1/notes/99", headers=_headers(session.user))
    assert resp.status_code == 404
    assert resp.json()["code"] == 40400


def test_patch_note_updates_title(client: TestClient) -> None:
    note = _note()
    session = FakeSession(user=_user(), note=note)
    _override(session)
    resp = client.patch(
        "/api/v1/notes/1", json={"title": "新标题"}, headers=_headers(session.user)
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "新标题"
    assert note.content_text == "正文"


def test_delete_note_returns_204_and_soft_deletes(client: TestClient) -> None:
    note = _note()
    session = FakeSession(user=_user(), note=note)
    _override(session)
    resp = client.delete("/api/v1/notes/1", headers=_headers(session.user))
    assert resp.status_code == 204
    assert resp.content == b""
    assert note.deleted_at is not None


def test_notes_require_token(client: TestClient) -> None:
    _override(FakeSession())
    resp = client.get("/api/v1/notes")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100