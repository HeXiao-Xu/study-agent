"""S2-6 上传/去重/补偿（FakeSession + FakeStorage，不连库不连网）。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import UploadFile

from app.core.exceptions import (
    ForbiddenError,
    InvalidParamError,
    NotFoundError,
    PayloadTooLargeError,
    StorageUnavailableError,
)
from app.models.file import File
from app.models.user import User
from app.models.user_relation import UserRelation
from app.services import file_service
from app.services.file_service import allows_parse_flag


class FakeSession:
    def __init__(
        self,
        *,
        existing: File | None = None,
        relation: int | None = None,
        commit_error: Exception | None = None,
        scalar_after_error: File | None = None,
    ) -> None:
        self.existing = existing
        self.relation = relation
        self.commit_error = commit_error
        self.scalar_after_error = scalar_after_error
        self.scalar_calls = 0
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is UserRelation:
            return self.relation
        self.scalar_calls += 1
        if self.scalar_calls > 1 and self.scalar_after_error is not None:
            return self.scalar_after_error
        return self.existing

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def get(self, entity: type, pk: int):
        return self.existing if entity is File else None

    def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, instance: object) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = 7
        instance.created_at = datetime.now(timezone.utc)


class FakeStorage:
    def __init__(self, *, object_present: bool = True, fail_put: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts: list[tuple[str, int, str]] = []
        self.deletes: list[str] = []
        self.object_present = object_present
        self.fail_put = fail_put

    def put(self, key: str, data, *, size: int, content_type: str) -> None:  # noqa: ANN001
        if self.fail_put:
            raise StorageUnavailableError()
        self.puts.append((key, size, content_type))
        self.objects[key] = data.read()

    def exists(self, key: str) -> bool:
        return self.object_present or key in self.objects

    def delete(self, key: str) -> None:
        self.deletes.append(key)
        self.objects.pop(key, None)


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


def _file(*, owner_id: int = 1, sha256: str | None = None) -> File:
    record = File(
        user_id=owner_id,
        filename="试卷.pdf",
        mime="application/pdf",
        size=8,
        storage_path=f"uploads/{owner_id}/aa/{sha256 or 'x' * 64}.pdf",
        sha256=sha256 or "x" * 64,
        parse_status="pending",
    )
    record.id = 5
    record.created_at = datetime.now(timezone.utc)
    return record


def _upload(content: bytes = b"%PDF-1.4\n", filename: str = "试卷.pdf") -> UploadFile:
    return UploadFile(file=BytesIO(content), filename=filename)


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        file_service,
        "get_settings",
        lambda: SimpleNamespace(
            upload_allowed_extensions="pdf,docx,md,txt,png,jpg,jpeg",
            upload_max_size_mb=60,
        ),
    )


def test_upload_new_file_writes_object_and_row() -> None:
    session, storage = FakeSession(), FakeStorage()
    record, deduped = file_service.upload_file(
        session, owner=_user(), upload=_upload(), storage=storage
    )
    digest = hashlib.sha256(b"%PDF-1.4\n").hexdigest()
    assert deduped is False
    assert record.user_id == 1
    assert record.sha256 == digest
    assert record.storage_path == f"uploads/1/{digest[:2]}/{digest}.pdf"
    assert record.size == 9
    assert record.parse_status == "pending"
    assert storage.puts == [(record.storage_path, 9, "application/pdf")]
    assert session.commits == 1


def test_upload_duplicate_reuses_row_without_put() -> None:
    digest = hashlib.sha256(b"%PDF-1.4\n").hexdigest()
    existing = _file(sha256=digest)
    session, storage = FakeSession(existing=existing), FakeStorage()
    record, deduped = file_service.upload_file(
        session, owner=_user(), upload=_upload(), storage=storage
    )
    assert (record is existing, deduped) == (True, True)
    assert storage.puts == []
    assert session.added == []


def test_upload_duplicate_with_missing_object_reuploads() -> None:
    digest = hashlib.sha256(b"%PDF-1.4\n").hexdigest()
    existing = _file(sha256=digest)
    session, storage = FakeSession(existing=existing), FakeStorage(object_present=False)
    record, deduped = file_service.upload_file(
        session, owner=_user(), upload=_upload(), storage=storage
    )
    assert (record is existing, deduped) == (True, False)
    assert len(storage.puts) == 1


def test_upload_oversize_raises_413(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        file_service,
        "get_settings",
        lambda: SimpleNamespace(upload_allowed_extensions="pdf", upload_max_size_mb=0),
    )
    with pytest.raises(PayloadTooLargeError) as excinfo:
        file_service.upload_file(
            FakeSession(), owner=_user(), upload=_upload(), storage=FakeStorage()
        )
    assert excinfo.value.code == 41300


def test_upload_rejects_bad_magic() -> None:
    with pytest.raises(InvalidParamError):
        file_service.upload_file(
            FakeSession(),
            owner=_user(),
            upload=_upload(b"plain text", "fake.pdf"),
            storage=FakeStorage(),
        )


def test_upload_rejects_unknown_extension() -> None:
    with pytest.raises(InvalidParamError):
        file_service.upload_file(
            FakeSession(),
            owner=_user(),
            upload=_upload(filename="run.exe"),
            storage=FakeStorage(),
        )


def test_upload_storage_failure_does_not_insert() -> None:
    session = FakeSession()
    with pytest.raises(StorageUnavailableError):
        file_service.upload_file(
            session, owner=_user(), upload=_upload(), storage=FakeStorage(fail_put=True)
        )
    assert session.added == []


def test_upload_db_failure_deletes_object() -> None:
    storage = FakeStorage()
    session = FakeSession(commit_error=RuntimeError("db down"))
    with pytest.raises(RuntimeError):
        file_service.upload_file(session, owner=_user(), upload=_upload(), storage=storage)
    assert len(storage.deletes) == 1
    assert session.rollbacks == 1


def test_upload_concurrent_conflict_returns_existing_without_delete() -> None:
    digest = hashlib.sha256(b"%PDF-1.4\n").hexdigest()
    winner = _file(sha256=digest)
    storage = FakeStorage()
    session = FakeSession(
        commit_error=IntegrityError("insert", {}, Exception("dup")),
        scalar_after_error=winner,
    )
    record, deduped = file_service.upload_file(
        session, owner=_user(), upload=_upload(), storage=storage
    )
    assert (record is winner, deduped) == (True, True)
    assert storage.deletes == []


def test_get_file_status_returns_own_file() -> None:
    record = _file()
    assert (
        file_service.get_file_status(
            FakeSession(existing=record), file_id=5, viewer=_user()
        )
        is record
    )


def test_get_file_status_missing_returns_404() -> None:
    with pytest.raises(NotFoundError):
        file_service.get_file_status(
            FakeSession(existing=None), file_id=5, viewer=_user()
        )


def test_get_file_status_other_returns_403() -> None:
    with pytest.raises(ForbiddenError):
        file_service.get_file_status(
            FakeSession(existing=_file(owner_id=1), relation=None),
            file_id=5,
            viewer=_user(2, username="student_b"),
        )


def test_get_file_status_allows_bound_parent() -> None:
    record = _file(owner_id=1)
    viewer = _user(3, role="parent", username="parent_1")
    assert (
        file_service.get_file_status(
            FakeSession(existing=record, relation=10), file_id=5, viewer=viewer
        )
        is record
    )


def test_parse_flag_allows_images_and_documents() -> None:
    assert allows_parse_flag(True, "text/markdown") is True
    assert allows_parse_flag(False, "image/png") is True
    assert allows_parse_flag(False, "application/pdf") is True
    assert allows_parse_flag(
        False,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ) is True


def test_parse_flag_still_rejects_plain_text_passthrough() -> None:
    assert allows_parse_flag(False, "text/markdown") is False
    assert allows_parse_flag(False, "text/plain") is False
