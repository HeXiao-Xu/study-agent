"""S2-1 模型契约测试：枚举值与 5 张表的字段/约束/索引与 SCHEMA + spec §4 一致。"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Identity,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector

import app.models as models_pkg
from app.models import (
    Base,
    KnowledgeEdge,
    KnowledgePoint,
    Subject,
    User,
    UserRelation,
)
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


_MODELS = (User, UserRelation, Subject, KnowledgePoint, KnowledgeEdge)

_EXPECTED_COLUMNS: dict[str, set[str]] = {
    "users": {
        "id",
        "username",
        "password_hash",
        "nickname",
        "grade",
        "role",
        "created_at",
        "updated_at",
    },
    "user_relations": {"id", "teacher_id", "student_id", "created_at", "updated_at"},
    "subjects": {"id", "name", "code", "stage", "config_json", "created_at", "updated_at"},
    "knowledge_points": {
        "id",
        "subject_id",
        "parent_id",
        "name",
        "code",
        "level",
        "description",
        "exam_weight",
        "embedding",
        "order_no",
        "created_at",
        "updated_at",
    },
    "knowledge_edges": {
        "id",
        "src_kp_id",
        "dst_kp_id",
        "relation",
        "weight",
        "source",
        "created_at",
        "updated_at",
    },
}

_NULLABLE: dict[str, set[str]] = {
    "users": {"grade"},
    "user_relations": set(),
    "subjects": {"config_json"},
    "knowledge_points": {"parent_id", "description", "exam_weight", "embedding"},
    "knowledge_edges": {"weight"},
}


def _checks(model: type[Base]) -> dict[str, str]:
    return {
        c.name: str(c.sqltext)
        for c in model.__table__.constraints
        if isinstance(c, CheckConstraint)
    }


def _uniques(model: type[Base]) -> dict[str, tuple[str, ...]]:
    return {
        c.name: tuple(col.name for col in c.columns)
        for c in model.__table__.constraints
        if isinstance(c, UniqueConstraint)
    }


def _indexes(model: type[Base]) -> dict[str, object]:
    return {i.name: i for i in model.__table__.indexes}


def _foreign_keys(model: type[Base]) -> dict[str, str]:
    return {fk.parent.name: fk.target_fullname for fk in model.__table__.foreign_keys}


def test_table_names_and_columns() -> None:
    for model in _MODELS:
        assert model.__tablename__ in _EXPECTED_COLUMNS
        assert set(model.__table__.columns.keys()) == _EXPECTED_COLUMNS[model.__tablename__]


def test_nullable_flags() -> None:
    for model in _MODELS:
        non_nullable = _EXPECTED_COLUMNS[model.__tablename__] - _NULLABLE[model.__tablename__]
        for name in non_nullable:
            assert model.__table__.columns[name].nullable is False, (
                model.__tablename__,
                name,
            )
        for name in _NULLABLE[model.__tablename__]:
            assert model.__table__.columns[name].nullable is True, (
                model.__tablename__,
                name,
            )


def test_primary_keys_are_bigint_identity() -> None:
    for model in _MODELS:
        pk = model.__table__.primary_key.columns["id"]
        assert isinstance(pk.type, BigInteger)
        assert isinstance(pk.identity, Identity)
        assert pk.identity.always is True


def test_timestamp_columns_default_and_onupdate() -> None:
    for model in _MODELS:
        created = model.__table__.columns["created_at"]
        updated = model.__table__.columns["updated_at"]
        assert isinstance(created.type, DateTime) and created.type.timezone is True
        assert str(created.server_default.arg) == "now()"
        assert isinstance(updated.type, DateTime) and updated.type.timezone is True
        assert str(updated.server_default.arg) == "now()"
        assert str(updated.onupdate.arg) == "now()"


def test_users_constraints() -> None:
    assert _uniques(User) == {"uq_users_username": ("username",)}
    assert _checks(User)["ck_users_role"] == in_check("role", UserRole)


def test_user_relations_constraints() -> None:
    assert _uniques(UserRelation) == {
        "uq_user_relations_teacher_student": ("teacher_id", "student_id")
    }
    assert "ck_user_relations_not_self" in _checks(UserRelation)
    assert _foreign_keys(UserRelation) == {
        "teacher_id": "users.id",
        "student_id": "users.id",
    }
    assert tuple(_indexes(UserRelation)["ix_user_relations_student_id"].columns.keys()) == (
        "student_id",
    )


def test_subjects_constraints() -> None:
    assert _uniques(Subject) == {"uq_subjects_code": ("code",)}
    stage = Subject.__table__.columns["stage"]
    assert str(stage.server_default.arg) == "'高中'"
    assert isinstance(Subject.__table__.columns["config_json"].type, JSONB)


def test_knowledge_points_constraints() -> None:
    assert _uniques(KnowledgePoint) == {
        "uq_knowledge_points_subject_code": ("subject_id", "code")
    }
    assert _checks(KnowledgePoint)["ck_knowledge_points_level"] == (
        "level >= 1 AND level <= 4"
    )
    assert _foreign_keys(KnowledgePoint) == {
        "subject_id": "subjects.id",
        "parent_id": "knowledge_points.id",
    }
    cols = KnowledgePoint.__table__.columns
    assert isinstance(cols["level"].type, SmallInteger)
    assert isinstance(cols["embedding"].type, Vector)
    assert cols["embedding"].type.dim == 1024
    assert isinstance(cols["exam_weight"].type, Numeric)
    assert isinstance(cols["order_no"].type, Integer)
    assert str(cols["order_no"].server_default.arg) == "0"


def test_knowledge_points_indexes() -> None:
    indexes = _indexes(KnowledgePoint)
    assert tuple(indexes["ix_knowledge_points_subject_id"].columns.keys()) == (
        "subject_id",
    )
    assert tuple(indexes["ix_knowledge_points_parent_id"].columns.keys()) == ("parent_id",)
    hnsw = indexes["ix_knowledge_points_embedding_hnsw"].dialect_options["postgresql"]
    assert hnsw["using"] == "hnsw"
    assert hnsw["ops"] == {"embedding": "vector_cosine_ops"}
    assert hnsw["with"] == {"m": 16, "ef_construction": 64}


def test_knowledge_edges_constraints() -> None:
    assert _uniques(KnowledgeEdge) == {
        "uq_knowledge_edges_src_dst_relation": ("src_kp_id", "dst_kp_id", "relation")
    }
    checks = _checks(KnowledgeEdge)
    assert checks["ck_knowledge_edges_relation"] == in_check("relation", EdgeRelation)
    assert checks["ck_knowledge_edges_source"] == in_check("source", EdgeSource)
    assert "ck_knowledge_edges_not_self" in checks
    assert _foreign_keys(KnowledgeEdge) == {
        "src_kp_id": "knowledge_points.id",
        "dst_kp_id": "knowledge_points.id",
    }
    assert tuple(_indexes(KnowledgeEdge)["ix_knowledge_edges_dst_kp_id"].columns.keys()) == (
        "dst_kp_id",
    )
    assert isinstance(KnowledgeEdge.__table__.columns["weight"].type, Numeric)


def test_models_registered_in_package() -> None:
    for name in (
        "User",
        "UserRelation",
        "Subject",
        "KnowledgePoint",
        "KnowledgeEdge",
    ):
        assert name in models_pkg.__all__