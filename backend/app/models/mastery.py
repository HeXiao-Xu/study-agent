"""掌握度（SCHEMA §6.3）。

一行 = 一个用户对一个知识点的掌握状态；没有行代表「未评估」，不是 0 掌握。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Mastery(Base):
    __tablename__ = "mastery"
    __table_args__ = (
        UniqueConstraint("user_id", "kp_id", name="uq_mastery_user_kp"),
        Index("ix_mastery_user_due", "user_id", "due_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_mastery_user_id", ondelete="CASCADE"),
        nullable=False,
    )
    kp_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_points.id", name="fk_mastery_kp_id", ondelete="CASCADE"),
        nullable=False,
    )
    mastery: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    correct_cnt: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    stability: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default=text("2")
    )
    last_practice_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )