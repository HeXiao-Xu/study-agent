"""作答（SCHEMA §6.2）。

一行 = 学生对一道题的一次作答；`paper_id` 非空时同卷同题只保留一行（自动保存 upsert），
`paper_id` 为空留给后续非试卷练习。草稿行 `is_correct/score/self_rated` 为 NULL，
交卷时一次写齐。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (
        CheckConstraint("score IS NULL OR score >= 0", name="ck_answers_score_nonneg"),
        CheckConstraint(
            "self_rated IS NULL OR self_rated IN (0, 0.5, 1)",
            name="ck_answers_self_rated",
        ),
        CheckConstraint(
            "time_spent_sec IS NULL OR time_spent_sec >= 0",
            name="ck_answers_time_nonneg",
        ),
        Index("ix_answers_user_question", "user_id", "question_id"),
        Index("ix_answers_paper_id", "paper_id"),
        Index(
            "uq_answers_user_paper_question",
            "user_id",
            "paper_id",
            "question_id",
            unique=True,
            postgresql_where=text("paper_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_answers_user_id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("questions.id", name="fk_answers_question_id", ondelete="RESTRICT"),
        nullable=False,
    )
    paper_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("papers.id", name="fk_answers_paper_id", ondelete="CASCADE"),
        nullable=True,
    )
    user_answer_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    self_rated: Mapped[Decimal | None] = mapped_column(Numeric(2, 1), nullable=True)
    time_spent_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )