"""knowledge_points ORM 模型：知识点树（SCHEMA §3.1，spec §4.4）。

embedding 本卡只建列不填（S2-10 知识点对齐时写入）。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.core.db import Base


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"
    __table_args__ = (
        UniqueConstraint("subject_id", "code", name="uq_knowledge_points_subject_code"),
        CheckConstraint("level >= 1 AND level <= 4", name="ck_knowledge_points_level"),
        Index("ix_knowledge_points_subject_id", "subject_id"),
        Index("ix_knowledge_points_parent_id", "parent_id"),
        Index(
            "ix_knowledge_points_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("subjects.id", name="fk_knowledge_points_subject_id"),
        nullable=False,
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_points.id", name="fk_knowledge_points_parent_id"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    exam_weight: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    order_no: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )