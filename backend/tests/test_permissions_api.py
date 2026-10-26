"""S2-3 权限集成测试：测试内临时 FastAPI 应用（spec §6.2）。

生产代码不新增任何接口；这里挂两条测试路由，验证依赖行为，
其中 test_b_cannot_read_a_notes_returns_403 是任务卡硬验收。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.exceptions import install_exception_handlers
from app.core.permissions import require_role, require_student_access
from app.core.security import create_access_token
from app.models.user import User
from app.models.user_relation import UserRelation


class FakeSession:
    def __init__(self, *, user: User, relation: int | None = None) -> None:
        self.user = user
        self.relation = relation

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        if entity is UserRelation:
            return self.relation
        raise AssertionError(f"unexpected statement: {statement}")


def _user(user_id: int, username: str, role: str) -> User:
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


A = _user(1, "student_a", "student")
B = _user(2, "student_b", "student")
PARENT = _user(3, "parent_1", "parent")
TEACHER = _user(4, "teacher_1", "teacher")
ADMIN = _user(5, "admin_1", "admin")


def _make_app() -> FastAPI:
    test_app = FastAPI()
    install_exception_handlers(test_app)

    @test_app.get("/students/{student_id}/notes")
    def student_notes(
        student_id: int, viewer: User = Depends(require_student_access)
    ) -> dict[str, object]:
        return {"owner_id": student_id, "viewer": viewer.username}

    @test_app.get("/admin/only")
    def admin_only(viewer: User = Depends(require_role("admin"))) -> dict[str, object]:
        return {"ok": True, "viewer": viewer.username}

    return test_app


def _client_for(user: User, *, relation: int | None = None) -> TestClient:
    test_app = _make_app()
    test_app.dependency_overrides[get_db] = lambda: FakeSession(user=user, relation=relation)
    return TestClient(test_app)


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


def test_a_can_read_a_notes() -> None:
    with _client_for(A) as client:
        resp = client.get("/students/1/notes", headers=_headers(A))
    assert resp.status_code == 200
    assert resp.json()["owner_id"] == 1


def test_b_cannot_read_a_notes_returns_403() -> None:
    with _client_for(B) as client:
        resp = client.get("/students/1/notes", headers=_headers(B))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert resp.json()["message"] == "无权访问该资源"


def test_bound_parent_can_read_student_notes() -> None:
    with _client_for(PARENT, relation=10) as client:
        resp = client.get("/students/1/notes", headers=_headers(PARENT))
    assert resp.status_code == 200


def test_unbound_parent_cannot_read_student_notes() -> None:
    with _client_for(PARENT, relation=None) as client:
        resp = client.get("/students/1/notes", headers=_headers(PARENT))
    assert resp.status_code == 403


def test_bound_teacher_can_read_student_notes() -> None:
    with _client_for(TEACHER, relation=11) as client:
        resp = client.get("/students/1/notes", headers=_headers(TEACHER))
    assert resp.status_code == 200


def test_admin_cannot_read_student_notes() -> None:
    with _client_for(ADMIN, relation=None) as client:
        resp = client.get("/students/1/notes", headers=_headers(ADMIN))
    assert resp.status_code == 403


def test_admin_can_read_admin_endpoint() -> None:
    with _client_for(ADMIN) as client:
        resp = client.get("/admin/only", headers=_headers(ADMIN))
    assert resp.status_code == 200


def test_student_cannot_read_admin_endpoint() -> None:
    with _client_for(A) as client:
        resp = client.get("/admin/only", headers=_headers(A))
    assert resp.status_code == 403


def test_missing_token_returns_401() -> None:
    with _client_for(A) as client:
        resp = client.get("/students/1/notes")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_unbound_parent_gets_403_even_for_missing_student() -> None:
    with _client_for(PARENT, relation=None) as client:
        resp = client.get("/students/999/notes", headers=_headers(PARENT))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300