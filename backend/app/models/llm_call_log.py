"""S3-7 模型：LLM/Embedding 调用日志，SCHEMA §8.4。"""
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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import LLMCallScene, LLMCallStatus, in_check


class LLMCallLog(Base):
    __tablename__ = "llm_call_logs"
    __table_args__ = (
        CheckConstraint(in_check("scene", LLMCallScene), name="ck_llm_call_logs_scene"),
        CheckConstraint(
            in_check("status", LLMCallStatus), name="ck_llm_call_logs_status"
        ),
        Index("ix_llm_call_logs_user_id_created_at", "user_id", "created_at"),
        Index("ix_llm_call_logs_scene", "scene"),
        Index("ix_llm_call_logs_trace_id", "trace_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "users.id",
            name="fk_llm_call_logs_user_id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    scene: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 8), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )