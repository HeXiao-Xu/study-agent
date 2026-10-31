"""S3-5 消息引用：SCHEMA §7.3。"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Identity, Index, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MessageCitation(Base):
    __tablename__ = "message_citations"
    __table_args__ = (Index("ix_message_citations_message_id", "message_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    message_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "messages.id",
            name="fk_message_citations_message_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    chunk_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    question_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)