"""错题诊断结果（SCHEMA §5.4）。S4-2 只建表，写入在 S4-3。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import CAUSE_TYPES, in_check


class MistakeAnalysis(Base):
    __tablename__ = "mistake_analyses"
    __table_args__ = (
        UniqueConstraint("mistake_id", name="uq_mistake_analyses_mistake_id"),
        CheckConstraint(in_check("cause_type", CAUSE_TYPES), name="ck_mistake_analyses_cause_type"),
        Index("ix_mistake_analyses_kp_ids", "kp_ids", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    mistake_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("mistakes.id", name="fk_mistake_analyses_mistake_id", ondelete="CASCADE"),
        nullable=False,
    )
    kp_ids: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger), nullable=True)
    cause_type: Mapped[str] = mapped_column(Text, nullable=False)
    error_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    similar_questions_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    review_advice_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )