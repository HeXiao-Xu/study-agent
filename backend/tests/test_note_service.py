"""S2-5 笔记服务测试（spec §8.2）：FakeSession，不连数据库。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.dialects import postgresql

from app.core.exceptions import ForbiddenError, InvalidParamError, NotFoundError
from app.models.note import Note
from app.models.subject import Subject
from app.models.user import User
from app.models.user_relation import UserRelation
from app.schemas.common import PageData
from app.schemas.notes import NoteCreate, NoteUpdate
from app.services import note_service
from app.utils.pagination import PageParams, SortParams


class FakeSession:
    def __init__(
        self,
        *,
        note: Note | None = None,
        relation: int | None = None,
        subject: Subject | None = None,
    ) -> None:
        self.note = note
        self.relation = relation
        self.subject = subject
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
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
        self.rollbacks += 1

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


def _note(note_id: int = 1, *, owner_id: int = 1, **overrides) -> Note:
    now = datetime.now(timezone.utc)
    note = Note(
        user_id=owner_id,
        subject_id=None,
        title="函数单调性",
        content_md="原正文 $x$",
        content_text="原正文",
        tags=["函数"],
        folder=None,
        source_file_id=None,
    )
    note.id = note_id
    note.created_at = now
    note.updated_at = now
    note.deleted_at = None
    for key, value in overrides.items():
        setattr(note, key, value)
    return note


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    box: dict[str, object] = {}

    def fake_paginate(session, stmt, params, *, item_model):
        box["stmt"] = stmt
        box["params"] = params
        return PageData(items=[], total=0, page=params.page, page_size=params.page_size)

    monkeypatch.setattr(note_service, "paginate_query", fake_paginate)
    return box


def _sql(stmt: object) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


def test_create_note_derives_content_text_and_normalizes_tags() -> None:
    session = FakeSession()
    note = note_service.create_note(
        session,
        owner=_user(),
        payload=NoteCreate(
            title="一元二次", content_md="设 $x^2$ 有解", tags=[" 函数 ", "函数", "方程"]
        ),
    )
    assert note.user_id == 1
    assert note.content_text == "设 有解"
    assert note.tags == ["函数", "方程"]
    assert session.commits == 1


def test_create_note_accepts_subject_and_folder() -> None:
    session = FakeSession(subject=Subject(name="数学", code="math"))
    note = note_service.create_note(
        session,
        owner=_user(),
        payload=NoteCreate(
            title="函数", content_md="正文", subject_id=3, folder="必修一"
        ),
    )
    assert (note.subject_id, note.folder) == (3, "必修一")


def test_create_note_rejects_missing_subject() -> None:
    session = FakeSession(subject=None)
    with pytest.raises(InvalidParamError) as excinfo:
        note_service.create_note(
            session,
            owner=_user(),
            payload=NoteCreate(title="函数", content_md="正文", subject_id=3),
        )
    assert excinfo.value.code == 42200


def test_list_notes_filters_owner_and_soft_deleted(captured: dict[str, object]) -> None:
    note_service.list_notes(
        FakeSession(), owner=_user(), params=PageParams(), sorting=SortParams()
    )
    sql = _sql(captured["stmt"])
    assert "notes.user_id =" in sql
    assert "notes.deleted_at IS NULL" in sql


def test_list_notes_filters_by_tag(captured: dict[str, object]) -> None:
    note_service.list_notes(
        FakeSession(),
        owner=_user(),
        params=PageParams(),
        sorting=SortParams(),
        tag="函数",
    )
    sql = _sql(captured["stmt"])
    assert "notes.tags @>" in sql


def test_list_notes_escapes_like_wildcards(captured: dict[str, object]) -> None:
    note_service.list_notes(
        FakeSession(), owner=_user(), params=PageParams(), sorting=SortParams(), q="100%"
    )
    compiled = captured["stmt"].compile(  # type: ignore[attr-defined]
        dialect=postgresql.dialect()
    )
    assert any("%100\\%%" in str(value) for value in compiled.params.values())


def test_list_notes_filters_by_time_range(captured: dict[str, object]) -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 12, 31, tzinfo=timezone.utc)
    note_service.list_notes(
        FakeSession(),
        owner=_user(),
        params=PageParams(),
        sorting=SortParams(),
        created_from=start,
        created_to=end,
    )
    sql = _sql(captured["stmt"])
    assert "notes.created_at >=" in sql
    assert "notes.created_at <=" in sql


def test_list_notes_defaults_to_created_at_desc(captured: dict[str, object]) -> None:
    note_service.list_notes(
        FakeSession(), owner=_user(), params=PageParams(), sorting=SortParams()
    )
    assert _sql(captured["stmt"]).rstrip().endswith("ORDER BY notes.created_at DESC")


def test_list_notes_rejects_unknown_sort_field(captured: dict[str, object]) -> None:
    with pytest.raises(InvalidParamError):
        note_service.list_notes(
            FakeSession(),
            owner=_user(),
            params=PageParams(),
            sorting=SortParams(sort_by="content_md"),
        )


def test_get_note_returns_own_note() -> None:
    note = _note()
    assert (
        note_service.get_note(FakeSession(note=note), note_id=1, viewer=_user()) is note
    )


def test_get_note_missing_returns_404() -> None:
    with pytest.raises(NotFoundError):
        note_service.get_note(FakeSession(note=None), note_id=1, viewer=_user())


def test_get_note_of_other_student_returns_403() -> None:
    session = FakeSession(note=_note(owner_id=1), relation=None)
    with pytest.raises(ForbiddenError):
        note_service.get_note(session, note_id=1, viewer=_user(2, username="student_b"))


def test_get_note_allows_bound_parent() -> None:
    note = _note(owner_id=1)
    session = FakeSession(note=note, relation=10)
    viewer = _user(3, role="parent", username="parent_1")
    assert note_service.get_note(session, note_id=1, viewer=viewer) is note


def test_update_note_title_only_keeps_content_text() -> None:
    note = _note()
    session = FakeSession(note=note)
    updated = note_service.update_note(
        session, note_id=1, owner=_user(), payload=NoteUpdate(title="新标题")
    )
    assert updated.title == "新标题"
    assert updated.content_text == "原正文"


def test_update_note_content_md_recomputes_content_text() -> None:
    note = _note()
    session = FakeSession(note=note)
    updated = note_service.update_note(
        session, note_id=1, owner=_user(), payload=NoteUpdate(content_md="新 $y$ 正文")
    )
    assert updated.content_md == "新 $y$ 正文"
    assert updated.content_text == "新 正文"


def test_update_note_of_other_returns_403() -> None:
    session = FakeSession(note=_note(owner_id=1))
    with pytest.raises(ForbiddenError):
        note_service.update_note(
            session,
            note_id=1,
            owner=_user(2, username="student_b"),
            payload=NoteUpdate(title="x"),
        )


def test_delete_note_sets_deleted_at() -> None:
    note = _note()
    session = FakeSession(note=note)
    note_service.delete_note(session, note_id=1, owner=_user())
    assert note.deleted_at is not None
    assert session.commits == 1


def test_delete_note_of_other_returns_403() -> None:
    session = FakeSession(note=_note(owner_id=1))
    with pytest.raises(ForbiddenError):
        note_service.delete_note(session, note_id=1, owner=_user(2, username="student_b"))