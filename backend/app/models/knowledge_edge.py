"""knowledge_edges ORM 模型：知识点关系边（SCHEMA §3.2，spec §4.5）。"""
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
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import EdgeRelation, EdgeSource, in_check


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"
    __table_args__ = (
        UniqueConstraint(
            "src_kp_id", "dst_kp_id", "relation", name="uq_knowledge_edges_src_dst_relation"
        ),
        CheckConstraint(
            in_check("relation", EdgeRelation), name="ck_knowledge_edges_relation"
        ),
        CheckConstraint(in_check("source", EdgeSource), name="ck_knowledge_edges_source"),
        CheckConstraint("src_kp_id <> dst_kp_id", name="ck_knowledge_edges_not_self"),
        Index("ix_knowledge_edges_dst_kp_id", "dst_kp_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    src_kp_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_points.id", name="fk_knowledge_edges_src_kp_id"),
        nullable=False,
    )
    dst_kp_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_points.id", name="fk_knowledge_edges_dst_kp_id"),
        nullable=False,
    )
    relation: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )