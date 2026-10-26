"""S2-1 模型契约测试：枚举值与 5 张表的字段/约束/索引与 SCHEMA + spec §4 一致。"""
from __future__ import annotations

from app.models.enums import EdgeRelation, EdgeSource, UserRole, in_check


def test_user_role_values_match_schema() -> None:
    assert {r.value for r in UserRole} == {"student", "teacher", "parent", "admin"}


def test_edge_relation_values_match_schema() -> None:
    assert {r.value for r in EdgeRelation} == {
        "prerequisite",
        "related",
        "confusable",
        "contains",
    }


def test_edge_source_values_match_schema() -> None:
    assert {r.value for r in EdgeSource} == {"ai", "manual"}


def test_in_check_renders_sql_in_list() -> None:
    assert in_check("role", UserRole) == (
        "role IN ('student', 'teacher', 'parent', 'admin')"
    )
    assert in_check("source", EdgeSource) == "source IN ('ai', 'manual')"