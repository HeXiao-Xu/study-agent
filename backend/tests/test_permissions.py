"""S2-3 权限单元测试：真值表、依赖工厂、服务层守卫（spec §6.1）。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.exceptions import ForbiddenError
from app.core.permissions import (
    can_access_student,
    ensure_student_access,
    has_student_relation,
    require_role,
)
from app.models.user import User
from app.models.user_relation import UserRelation


class FakeSession:
    """只回答两种查询：select(User) 与 select(UserRelation.id)。"""

    def __init__(self, *, user: User | None = None, relation: int | None = None) -> None:
        self.user = user
        self.relation = relation
        self.statements: list[object] = []

    def scalar(self, statement: object):
        self.statements.append(statement)
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        if entity is UserRelation:
            return self.relation
        raise AssertionError(f"unexpected statement: {statement}")


def _user(user_id: int, role: str) -> User:
    user = User(
        username=f"user_{user_id}",
        password_hash="hash",
        nickname=f"测试用户_{user_id}",
        grade="高一",
        role=role,
    )
    user.id = user_id
    user.created_at = datetime.now(timezone.utc)
    return user


STUDENT_A = _user(1, "student")
STUDENT_B = _user(2, "student")
PARENT = _user(3, "parent")
TEACHER = _user(4, "teacher")
ADMIN = _user(5, "admin")


def test_self_can_access_own_data() -> None:
    session = FakeSession(user=STUDENT_A)
    assert can_access_student(session, STUDENT_A, STUDENT_A.id) is True
    assert session.statements == []  # 本人直接放行，不查关系表


def test_bound_parent_can_access_student() -> None:
    session = FakeSession(user=PARENT, relation=10)
    assert can_access_student(session, PARENT, STUDENT_A.id) is True


def test_unbound_parent_cannot_access_student() -> None:
    session = FakeSession(user=PARENT, relation=None)
    assert can_access_student(session, PARENT, STUDENT_A.id) is False


def test_bound_teacher_can_access_student() -> None:
    session = FakeSession(user=TEACHER, relation=11)
    assert can_access_student(session, TEACHER, STUDENT_A.id) is True


def test_unbound_teacher_cannot_access_student() -> None:
    session = FakeSession(user=TEACHER, relation=None)
    assert can_access_student(session, TEACHER, STUDENT_A.id) is False


def test_other_student_cannot_access() -> None:
    session = FakeSession(user=STUDENT_B)
    assert can_access_student(session, STUDENT_B, STUDENT_A.id) is False
    assert session.statements == []  # 学生角色不查关系表


def test_admin_does_not_bypass_student_access() -> None:
    session = FakeSession(user=ADMIN, relation=None)
    assert can_access_student(session, ADMIN, STUDENT_A.id) is False


def test_admin_can_access_own_data() -> None:
    session = FakeSession(user=ADMIN)
    assert can_access_student(session, ADMIN, ADMIN.id) is True


def test_ensure_student_access_raises_403_for_outsider() -> None:
    session = FakeSession(user=STUDENT_B)
    with pytest.raises(ForbiddenError) as excinfo:
        ensure_student_access(session, STUDENT_B, STUDENT_A.id)
    assert excinfo.value.code == 40300
    assert excinfo.value.message == "无权访问该资源"


def test_ensure_student_access_passes_for_bound_parent() -> None:
    session = FakeSession(user=PARENT, relation=10)
    ensure_student_access(session, PARENT, STUDENT_A.id)


def test_require_role_rejects_unknown_role_name() -> None:
    with pytest.raises(ValueError):
        require_role("admn")


def test_require_role_allows_and_denies() -> None:
    dependency = require_role("admin")
    assert dependency(ADMIN) is ADMIN
    with pytest.raises(ForbiddenError) as excinfo:
        dependency(STUDENT_A)
    assert excinfo.value.code == 40300


def test_has_student_relation_hit_and_miss() -> None:
    assert (
        has_student_relation(FakeSession(user=PARENT, relation=10), viewer_id=3, student_id=1)
        is True
    )
    assert (
        has_student_relation(FakeSession(user=PARENT, relation=None), viewer_id=3, student_id=1)
        is False
    )