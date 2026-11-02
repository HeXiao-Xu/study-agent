"""S4-1 题库表结构：约束与索引是判重/检索的前提，必须由迁移固化。"""
from __future__ import annotations

from sqlalchemy import UniqueConstraint

from app.models import Base
from app.models.question import Question
from app.models.question_kp import QuestionKp


def test_questions_has_stem_hash_and_unique() -> None:
    table = Base.metadata.tables["questions"]
    assert "stem_hash" in table.columns
    assert table.columns["stem_hash"].nullable is False
    uniques = [c for c in table.constraints if isinstance(c, UniqueConstraint)]
    assert any(set(c.columns.keys()) == {"subject_id", "stem_hash"} for c in uniques)


def test_questions_check_constraints_cover_enums() -> None:
    checks = " ".join(
        str(c.sqltext) for c in Base.metadata.tables["questions"].constraints
        if type(c).__name__ == "CheckConstraint"
    )
    assert "origin IN" in checks and "'upload'" in checks
    assert "qtype IN" in checks and "'单选'" in checks
    assert "difficulty >= 1" in checks


def test_questions_indexes() -> None:
    indexes = Base.metadata.tables["questions"].indexes
    names = {ix.name for ix in indexes}
    assert {"ix_questions_subject_id", "ix_questions_origin", "ix_questions_qtype",
            "ix_questions_tags", "ix_questions_embedding_hnsw"} <= names
    hnsw = next(ix for ix in indexes if ix.name == "ix_questions_embedding_hnsw")
    assert hnsw.dialect_options["postgresql"]["using"] == "hnsw"
    assert hnsw.dialect_options["postgresql"]["ops"] == {"embedding": "vector_cosine_ops"}


def test_question_kps_composite_pk_and_cascade() -> None:
    table = Base.metadata.tables["question_kps"]
    assert list(table.primary_key.columns.keys()) == ["question_id", "kp_id"]
    for fk in table.foreign_keys:
        assert fk.ondelete == "CASCADE"
    assert {ix.name for ix in table.indexes} == {"ix_question_kps_kp_id"}


def test_question_defaults() -> None:
    question = Question(subject_id=1, stem_md="测试题干内容", stem_hash="h", qtype="单选", difficulty=3)
    assert question.verified is None or question.verified is False
    assert QuestionKp(question_id=1, kp_id=2).weight is None