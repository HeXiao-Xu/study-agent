"""note_kps ORM 模型：SCHEMA §4.4（S2-5 只建表，对齐逻辑在 S2-10）。"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class NoteKp(Base):
    __tablename__ = "note_kps"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="ck_note_kps_source"),
        Index("ix_note_kps_kp_id", "kp_id"),
    )

    note_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("notes.id", name="fk_note_kps_note_id", ondelete="CASCADE"),
        primary_key=True,
    )
    kp_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_points.id", name="fk_note_kps_kp_id"),
        primary_key=True,
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )