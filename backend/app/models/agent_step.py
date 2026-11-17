"""agent_steps ORM 模型（SCHEMA §8.2，S6-2）。

每个图节点执行后写一行；`step_no` 从 1 连续递增，支撑回放与前端时间线。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import AGENT_STEP_STATUSES, in_check


class AgentStep(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint("task_id", "step_no", name="uq_agent_steps_task_step"),
        CheckConstraint(
            in_check("status", AGENT_STEP_STATUSES), name="ck_agent_steps_status"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("agent_tasks.id", name="fk_agent_steps_task_id", ondelete="CASCADE"),
        nullable=False,
    )
    step_no: Mapped[int] = mapped_column(Integer, nullable=False)
    thought: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_input_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    tool_output_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
