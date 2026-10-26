"""user_relations ORM 模型：老师/家长绑定学生（SCHEMA §2.2，spec §4.2）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UserRelation(Base):
    __tablename__ = "user_relations"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id", "student_id", name="uq_user_relations_teacher_student"
        ),
        CheckConstraint("teacher_id <> student_id", name="ck_user_relations_not_self"),
        Index("ix_user_relations_student_id", "student_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_user_relations_teacher_id"),
        nullable=False,
    )
    student_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_user_relations_student_id"),
        nullable=False,
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