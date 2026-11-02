"""错题（SCHEMA §5.3）。

user_id + question_id 唯一：同一学生对同一题只保留一条错题，再错一次是
「复用并重置」，不是新增一条（spec D-1）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import MISTAKE_STATUSES, MistakeStatus, in_check


class Mistake(Base):
    __tablename__ = "mistakes"
    __table_args__ = (
        UniqueConstraint("user_id", "question_id", name="uq_mistakes_user_question"),
        CheckConstraint(in_check("status", MISTAKE_STATUSES), name="ck_mistakes_status"),
        CheckConstraint("correct_streak >= 0", name="ck_mistakes_correct_streak"),
        Index("ix_mistakes_user_status", "user_id", "status"),
        Index("ix_mistakes_user_created", "user_id", "created_at"),
        Index("ix_mistakes_question_id", "question_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_mistakes_user_id"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("questions.id", name="fk_mistakes_question_id", ondelete="RESTRICT"),
        nullable=False,
    )
    my_answer_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    correct_answer_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_file_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("files.id", name="fk_mistakes_image_file_id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text(f"'{MistakeStatus.TODO.value}'")
    )
    correct_streak: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )