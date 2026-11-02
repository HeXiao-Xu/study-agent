"""questions ORM 模型：题库（SCHEMA §5.1，spec §7）。

stem_hash 是判重第一道闸：迁移里建 UNIQUE(subject_id, stem_hash)，
service 只依赖该约束，不自己保证唯一（并发下只有 DB 约束可信）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import QuestionOrigin, QuestionType, in_check

_ORIGINS = [item.value for item in QuestionOrigin]
_QTYPES = [item.value for item in QuestionType]


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("subject_id", "stem_hash", name="uq_questions_subject_stem_hash"),
        CheckConstraint(in_check("origin", _ORIGINS), name="ck_questions_origin"),
        CheckConstraint(in_check("qtype", _QTYPES), name="ck_questions_qtype"),
        CheckConstraint("difficulty >= 1 AND difficulty <= 5", name="ck_questions_difficulty"),
        Index("ix_questions_subject_id", "subject_id"),
        Index("ix_questions_origin", "origin"),
        Index("ix_questions_qtype", "qtype"),
        Index("ix_questions_tags", "tags", postgresql_using="gin"),
        Index(
            "ix_questions_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("subjects.id", name="fk_questions_subject_id"), nullable=False
    )
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'upload'"))
    source_file_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("files.id", name="fk_questions_source_file_id"), nullable=True
    )
    stem_md: Mapped[str] = mapped_column(Text, nullable=False)
    stem_latex: Mapped[str | None] = mapped_column(Text, nullable=True)
    stem_hash: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    answer_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    qtype: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("3"))
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_questions_created_by"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )