"""question_kps ORM 模型：题目↔知识点（SCHEMA §5.2，spec §7）。

weight 存对齐打分的原始分（0–1），人工指定固定 1.0；
不叫 confidence，避免与 note_kps.confidence 的语义（LLM 自置信度）混淆。
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Index, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class QuestionKp(Base):
    __tablename__ = "question_kps"
    __table_args__ = (Index("ix_question_kps_kp_id", "kp_id"),)

    question_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("questions.id", name="fk_question_kps_question_id", ondelete="CASCADE"),
        primary_key=True,
    )
    kp_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_points.id", name="fk_question_kps_kp_id", ondelete="CASCADE"),
        primary_key=True,
    )
    weight: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)