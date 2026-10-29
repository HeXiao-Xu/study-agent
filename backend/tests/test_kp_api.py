"""S2-9 知识点接口：TestClient + FakeSession。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.knowledge_point import KnowledgePoint
from app.models.subject import Subject
from app.models.user import User
from app.services import kp_service


class FakeSession:
    def __init__(
        self,
        *,
        user: User | None = None,
        subject: Subject | None = None,
        rows: list[KnowledgePoint] | None = None,
        get_map: dict[int, KnowledgePoint] | None = None,
        duplicate: bool = False,
        has_child: bool = False,
    ) -> None:
        self.user = user
        self.subject = subject
        self.rows = rows or []
        self.get_map = get_map or {}
        self.duplicate = duplicate
        self.has_child = has_child
        self.added: list[KnowledgePoint] = []
        self.deleted: list[KnowledgePoint] = []
        self.commits = 0

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        sql = str(statement)
        if entity is User:
            return self.user
        if entity is Subject:
            return self.subject
        if "FROM note_kps" in sql or "FROM knowledge_edges" in sql:
            return None
        if entity is KnowledgePoint:
            if "parent_id" in sql:
                return 1 if self.has_child else None
            return 1 if self.duplicate else None
        raise AssertionError(f"unexpected scalar: {sql}")

    def scalars(self, statement: object):
        return list(self.rows)

    def get(self, entity: type, pk: int):
        if entity is KnowledgePoint:
            return self.get_map.get(pk)
        raise AssertionError(f"unexpected get: {entity}")

    def add(self, instance: KnowledgePoint) -> None:
        self.added.append(instance)

    def flush(self) -> None:
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = 100

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def refresh(self, instance: object) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = 100

    def delete(self, instance: KnowledgePoint) -> None:
        self.deleted.append(instance)


def _user(role: str = "teacher", user_id: int = 1) -> User:
    user = User(
        username=f"{role}_kp",
        password_hash="hash",
        nickname=f"测试用户_{user_id}",
        grade="高一",
        role=role,
    )
    user.id = user_id
    user.created_at = datetime.now(timezone.utc)
    return user


def _subject() -> Subject:
    subject = Subject(name="高中数学", code="math", stage="高中")
    subject.id = 1
    return subject


def _kp(kp_id: int, code: str, level: int, parent_id: int | None = None) -> KnowledgePoint:
    kp = KnowledgePoint(
        subject_id=1,
        parent_id=parent_id,
        name=code,
        code=code,
        level=level,
        description=None,
        exam_weight=None,
        order_no=0,
    )
    kp.id = kp_id
    return kp


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(session: FakeSession) -> None:
    app.dependency_overrides[get_db] = lambda: session


def test_list_subjects_returns_subjects(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user, subject=_subject(), rows=[_subject()]))
    resp = client.get("/api/v1/kp/subjects", headers=_headers(user))
    assert resp.status_code == 200
    assert resp.json()["data"][0]["code"] == "math"


def test_tree_returns_nested_nodes(client: TestClient) -> None:
    user = _user()
    _wire(
        FakeSession(
            user=user,
            subject=_subject(),
            rows=[_kp(1, "MATH", 1), _kp(2, "MATH-SET", 2, 1)],
        )
    )
    resp = client.get("/api/v1/kp/tree?subject=math", headers=_headers(user))
    assert resp.status_code == 200
    nodes = resp.json()["data"]["nodes"]
    assert nodes[0]["children"][0]["code"] == "MATH-SET"


def test_tree_missing_subject_param_returns_422(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    resp = client.get("/api/v1/kp/tree", headers=_headers(user))
    assert resp.status_code == 422


def test_tree_unknown_subject_returns_404(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    resp = client.get("/api/v1/kp/tree?subject=nope", headers=_headers(user))
    assert resp.status_code == 404


def test_create_kp_forbidden_for_student(client: TestClient) -> None:
    user = _user(role="student")
    _wire(FakeSession(user=user, subject=_subject()))
    resp = client.post(
        "/api/v1/kp",
        json={"subject": "math", "code": "MATH-X", "name": "X"},
        headers=_headers(user),
    )
    assert resp.status_code == 403


def test_create_kp_teacher_returns_201(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user, subject=_subject()))
    resp = client.post(
        "/api/v1/kp",
        json={"subject": "math", "code": "MATH-X", "name": "X"},
        headers=_headers(user),
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["level"] == 1


def test_create_kp_duplicate_code_returns_409(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user, subject=_subject(), duplicate=True))
    resp = client.post(
        "/api/v1/kp",
        json={"subject": "math", "code": "MATH-X", "name": "X"},
        headers=_headers(user),
    )
    assert resp.status_code == 409


def test_patch_kp_moves_and_returns_level(client: TestClient) -> None:
    user = _user()
    kp = _kp(1, "MATH-A", 1)
    parent = _kp(2, "MATH-B", 1)
    _wire(FakeSession(user=user, rows=[kp, parent], get_map={1: kp, 2: parent}))
    resp = client.patch(
        "/api/v1/kp/1", json={"parent_id": 2}, headers=_headers(user)
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["level"] == 2


def test_delete_kp_with_children_returns_409(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user, get_map={1: _kp(1, "MATH", 1)}, has_child=True))
    resp = client.delete("/api/v1/kp/1", headers=_headers(user))
    assert resp.status_code == 409


def test_delete_leaf_returns_204(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user, get_map={1: _kp(1, "MATH", 1)}))
    resp = client.delete("/api/v1/kp/1", headers=_headers(user))
    assert resp.status_code == 204

def test_reorder_kp_teacher_returns_204(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    captured: dict[str, object] = {}

    def fake_reorder(session, *, parent_id, ordered_ids, moved_id=None):
        captured.update(
            parent_id=parent_id,
            ordered_ids=ordered_ids,
            moved_id=moved_id,
        )

    monkeypatch.setattr(kp_service, "reorder_children", fake_reorder)
    resp = client.put(
        "/api/v1/kp/order",
        json={"parent_id": 1, "ordered_ids": [3, 2], "moved_id": 3},
        headers=_headers(user),
    )
    assert resp.status_code == 204
    assert resp.content == b""
    assert captured == {"parent_id": 1, "ordered_ids": [3, 2], "moved_id": 3}


def test_reorder_kp_accepts_root_parent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    captured: dict[str, object] = {}

    def fake_reorder(session, *, parent_id, ordered_ids, moved_id=None):
        captured.update(parent_id=parent_id, ordered_ids=ordered_ids)

    monkeypatch.setattr(kp_service, "reorder_children", fake_reorder)
    resp = client.put(
        "/api/v1/kp/order",
        json={"parent_id": None, "ordered_ids": [2, 1]},
        headers=_headers(user),
    )
    assert resp.status_code == 204
    assert captured["parent_id"] is None


def test_reorder_kp_forbidden_for_student(client: TestClient) -> None:
    user = _user(role="student")
    _wire(FakeSession(user=user))
    resp = client.put(
        "/api/v1/kp/order",
        json={"parent_id": 1, "ordered_ids": [2]},
        headers=_headers(user),
    )
    assert resp.status_code == 403


def test_reorder_kp_rejects_empty_order(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    resp = client.put(
        "/api/v1/kp/order",
        json={"parent_id": 1, "ordered_ids": []},
        headers=_headers(user),
    )
    assert resp.status_code == 422
