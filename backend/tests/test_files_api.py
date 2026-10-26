"""S2-6 文件接口：TestClient + 依赖覆盖，不连库不连 MinIO。"""
from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.core.storage import get_storage
from app.main import app
from app.models.file import File
from app.models.user import User
from app.models.user_relation import UserRelation
from app.services import file_service
from app.tasks.parse_document import TASK_PARSE_DOCUMENT
from app.tasks.queue import get_task_queue

_PDF_BYTES = b"%PDF-1.4\n"
_DIGEST = hashlib.sha256(_PDF_BYTES).hexdigest()


class FakeSession:
    def __init__(
        self,
        *,
        user: User | None = None,
        record: File | None = None,
        relation: int | None = None,
    ) -> None:
        self.user = user
        self.record = record
        self.relation = relation
        self.added: list[object] = []
        self.commits = 0

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        if entity is UserRelation:
            return self.relation
        return self.record

    def get(self, entity: type, pk: int):
        return self.record if entity is File else None

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def refresh(self, instance: object) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = 11
        instance.created_at = datetime.now(timezone.utc)


class FakeQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def enqueue(self, name: str, task_id: int) -> None:
        self.calls.append((name, task_id))


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []

    def put(self, key: str, data, *, size: int, content_type: str) -> None:  # noqa: ANN001
        self.puts.append(key)
        self.objects[key] = data.read()

    def exists(self, key: str) -> bool:
        return key in self.objects

    def delete(self, key: str) -> None:
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


def _record(*, owner_id: int = 1, status: str = "pending") -> File:
    record = File(
        user_id=owner_id,
        filename="试卷.pdf",
        mime="application/pdf",
        size=len(_PDF_BYTES),
        storage_path=f"uploads/{owner_id}/{_DIGEST[:2]}/{_DIGEST}.pdf",
        sha256=_DIGEST,
        parse_status=status,
        parse_progress=0,
        error_msg=None,
    )
    record.id = 11
    record.created_at = datetime.now(timezone.utc)
    return record


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


def _file_payload() -> dict[str, tuple[str, BytesIO, str]]:
    return {"file": ("试卷.pdf", BytesIO(_PDF_BYTES), "application/pdf")}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(session: FakeSession, storage: FakeStorage | None = None) -> FakeQueue:
    store = storage or FakeStorage()
    queue = FakeQueue()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_storage] = lambda: store
    app.dependency_overrides[get_task_queue] = lambda: queue
    return queue


def test_upload_returns_201_and_deduped_false(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    resp = client.post("/api/v1/files", files=_file_payload(), headers=_headers(user))
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["deduped"] is False
    assert data["parse_status"] == "pending"
    assert "storage_path" not in data


def test_upload_duplicate_returns_200_and_same_id(client: TestClient) -> None:
    user = _user()
    session = FakeSession(user=user, record=_record())
    storage = FakeStorage()
    storage.objects[_record().storage_path] = _PDF_BYTES
    _wire(session, storage)
    resp = client.post("/api/v1/files", files=_file_payload(), headers=_headers(user))
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == 11
    assert resp.json()["data"]["deduped"] is True
    assert storage.puts == []


def test_upload_oversize_returns_413(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    monkeypatch.setattr(
        file_service,
        "get_settings",
        lambda: SimpleNamespace(upload_allowed_extensions="pdf", upload_max_size_mb=0),
    )
    resp = client.post("/api/v1/files", files=_file_payload(), headers=_headers(user))
    assert resp.status_code == 413
    assert resp.json()["code"] == 41300


def test_upload_bad_extension_returns_422(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    resp = client.post(
        "/api/v1/files",
        files={"file": ("run.exe", BytesIO(b"MZ"), "application/octet-stream")},
        headers=_headers(user),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_upload_missing_field_returns_400(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    resp = client.post("/api/v1/files", data={}, headers=_headers(user))
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_upload_requires_token(client: TestClient) -> None:
    _wire(FakeSession())
    resp = client.post("/api/v1/files", files=_file_payload())
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_upload_forbidden_for_teacher(client: TestClient) -> None:
    user = _user(role="teacher", username="teacher_1")
    _wire(FakeSession(user=user))
    resp = client.post("/api/v1/files", files=_file_payload(), headers=_headers(user))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_parse_status_returns_pending(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user, record=_record()))
    resp = client.get("/api/v1/files/11/parse-status", headers=_headers(user))
    assert resp.status_code == 200
    assert resp.json()["data"] == {
        "id": 11,
        "filename": "试卷.pdf",
        "parse_status": "pending",
        "parse_progress": 0,
        "error_msg": None,
    }


def test_parse_status_missing_returns_404(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user, record=None))
    resp = client.get("/api/v1/files/99/parse-status", headers=_headers(user))
    assert resp.status_code == 404
    assert resp.json()["code"] == 40400


def test_parse_status_other_user_returns_403(client: TestClient) -> None:
    user = _user(2, username="student_b")
    _wire(FakeSession(user=user, record=_record(owner_id=1), relation=None))
    resp = client.get("/api/v1/files/11/parse-status", headers=_headers(user))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300

def test_upload_enqueues_parse_task(client: TestClient) -> None:
    user = _user()
    queue = _wire(FakeSession(user=user))
    resp = client.post("/api/v1/files", files=_file_payload(), headers=_headers(user))
    assert resp.status_code == 201
    assert queue.calls == [(TASK_PARSE_DOCUMENT, 11)]


def test_upload_duplicate_done_does_not_enqueue(client: TestClient) -> None:
    user = _user()
    session = FakeSession(user=user, record=_record(status="done"))
    storage = FakeStorage()
    storage.objects[_record().storage_path] = _PDF_BYTES
    queue = _wire(session, storage)
    resp = client.post("/api/v1/files", files=_file_payload(), headers=_headers(user))
    assert resp.status_code == 200
    assert queue.calls == []


def test_upload_duplicate_failed_reenqueues(client: TestClient) -> None:
    user = _user()
    session = FakeSession(user=user, record=_record(status="failed"))
    storage = FakeStorage()
    storage.objects[_record().storage_path] = _PDF_BYTES
    queue = _wire(session, storage)
    resp = client.post("/api/v1/files", files=_file_payload(), headers=_headers(user))
    assert resp.status_code == 200
    assert queue.calls == [(TASK_PARSE_DOCUMENT, 11)]


def test_parse_status_returns_progress_and_error(client: TestClient) -> None:
    user = _user()
    record = _record(status="failed")
    record.parse_progress = 50
    record.error_msg = "RuntimeError: bad pdf"
    _wire(FakeSession(user=user, record=record))
    resp = client.get("/api/v1/files/11/parse-status", headers=_headers(user))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["parse_progress"] == 50
    assert data["error_msg"] == "RuntimeError: bad pdf"
