"""错题诊断结果（SCHEMA §5.4）。S4-2 建表，S4-3 写入并增次因/置信度。"""
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import CAUSE_TYPES, in_check

_CAUSE_ARRAY_SQL = (
    "ARRAY['概念不清','计算失误','审题偏差','方法不当','知识遗忘','时间不足','unknown']::text[]"
)


class MistakeAnalysis(Base):
    __tablename__ = "mistake_analyses"
    __table_args__ = (
        UniqueConstraint("mistake_id", name="uq_mistake_analyses_mistake_id"),
        CheckConstraint(in_check("cause_type", CAUSE_TYPES), name="ck_mistake_analyses_cause_type"),
        CheckConstraint(
            f"secondary_causes IS NULL OR secondary_causes <@ {_CAUSE_ARRAY_SQL}",
            name="ck_mistake_analyses_secondary_causes",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_mistake_analyses_confidence",
        ),
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
    # 次因至多 2 个（服务层截断），元素必须是 CauseType 值集之一（DB CHECK 兜底）
    secondary_causes: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    error_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    similar_questions_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    review_advice_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    # LLM 自评置信度；用 NUMERIC 而不是 float，避免统计时浮点误差
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )