"""复习清单项（SCHEMA §6.4，S5-5）。

一 kp 一条待办：唯一键保证刷新幂等；ref_id 是多态引用，故意不建外键，
资源被硬删后仍保留行，由接口给 ref_available=false。
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
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import REVIEW_REF_TYPES, in_check


class ReviewItem(Base):
    __tablename__ = "review_items"
    __table_args__ = (
        UniqueConstraint("user_id", "kp_id", name="uq_review_items_user_kp"),
        CheckConstraint(in_check("ref_type", REVIEW_REF_TYPES), name="ck_review_items_ref_type"),
        CheckConstraint(
            "interval_days >= 1 AND interval_days <= 30",
            name="ck_review_items_interval",
        ),
        CheckConstraint(
            "priority IS NULL OR (priority >= 0 AND priority <= 1)",
            name="ck_review_items_priority",
        ),
        Index("ix_review_items_user_due", "user_id", "due_at"),
        Index("ix_review_items_user_done", "user_id", "done_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_review_items_user_id", ondelete="CASCADE"),
        nullable=False,
    )
    kp_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "knowledge_points.id", name="fk_review_items_kp_id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    ref_type: Mapped[str] = mapped_column(Text, nullable=False)
    ref_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)