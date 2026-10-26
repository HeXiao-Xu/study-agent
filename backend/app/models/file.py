"""files ORM 模型：SCHEMA §4.1（S2-5 建表，S2-6 接上传）。

sha256 唯一性定「同用户唯一」：多租户下不同用户上传同一份文件互不可见，
同一用户重复上传才复用。
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
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class File(Base):
    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("user_id", "sha256", name="uq_files_user_sha256"),
        CheckConstraint(
            "parse_status IN ('pending', 'done')", name="ck_files_parse_status"
        ),
        Index("ix_files_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_files_user_id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    parse_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    parse_result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )