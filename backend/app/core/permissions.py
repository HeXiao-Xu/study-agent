"""S2-3 RBAC 与数据隔离（spec §4）。

为什么只做依赖、不做装饰器：FastAPI 依赖可组合、自动进 OpenAPI，
测试里能用 dependency_overrides 替换；装饰器会把参数与返回类型藏起来。

为什么 admin 不绕过 require_student_access：管理端有自己的 require_role("admin")
接口；若这里放行 admin，任何普通学生数据接口都会变成管理员的隐式全量读口子。
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.exceptions import ForbiddenError
from app.models.enums import UserRole
from app.models.user import User
from app.models.user_relation import UserRelation

_VIEWER_ROLES = frozenset({UserRole.PARENT.value, UserRole.TEACHER.value})
_ALL_ROLES = frozenset(member.value for member in UserRole)


def require_role(*roles: str) -> Callable[..., User]:
    """管理接口用：只有列出的角色可进。

    角色名在工厂阶段校验：拼错立即 ValueError，不留到运行期变成静默 403。
    """
    allowed = frozenset(roles)
    unknown = allowed - _ALL_ROLES
    if unknown:
        raise ValueError(f"未知角色：{', '.join(sorted(unknown))}")
    if not allowed:
        raise ValueError("require_role 至少需要一个角色")

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed:
            raise ForbiddenError("无权访问该资源")
        return current_user

    return dependency


def has_student_relation(session: Session, *, viewer_id: int, student_id: int) -> bool:
    """查看方是否已绑定该学生（user_relations.teacher_id 语义为“查看方”）。"""
    stmt = select(UserRelation.id).where(
        UserRelation.teacher_id == viewer_id,
        UserRelation.student_id == student_id,
    )
    return session.scalar(stmt) is not None


def can_access_student(session: Session, viewer: User, student_id: int) -> bool:
    if viewer.id == student_id:
        return True
    if viewer.role not in _VIEWER_ROLES:
        return False
    return has_student_relation(session, viewer_id=viewer.id, student_id=student_id)


def ensure_student_access(session: Session, viewer: User, student_id: int) -> None:
    """service 层用：资源的 user_id 来自数据库时，先拿它调这里再继续查/改。"""
    if not can_access_student(session, viewer, student_id):
        raise ForbiddenError("无权访问该资源")


def require_student_access(
    student_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> User:
    """路由依赖：本人或已绑定家长/老师放行。

    只能用于路径含 ``{student_id}`` 的路由（FastAPI 按同名参数从路径注入）；
    若路径没有该参数，FastAPI 会把它当 query 参数——此时请改用
    ensure_student_access()。
    """
    ensure_student_access(session, current_user, student_id)
    return current_user