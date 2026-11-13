"""papers ORM 模型：组卷结果（SCHEMA §6.1，S5-2）。

question_ids 存有序题目 id：卷面顺序就是数组顺序，换题/重排只改数组；
S5-4 的 answers 再按 (paper_id, question_id) 关联，不建中间表。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import PaperGeneratedBy, PaperStatus, in_check

_STATUSES = [item.value for item in PaperStatus]
_GENERATED_BY = [item.value for item in PaperGeneratedBy]


class Paper(Base):
    __tablename__ = "papers"
    __table_args__ = (
        CheckConstraint(in_check("status", _STATUSES), name="ck_papers_status"),
        CheckConstraint(
            in_check("generated_by", _GENERATED_BY), name="ck_papers_generated_by"
        ),
        Index("ix_papers_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_papers_user_id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    constraint_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    question_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    total_score: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=PaperStatus.DRAFT.value
    )
    generated_by: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=PaperGeneratedBy.MANUAL.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )