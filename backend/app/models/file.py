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
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import ParseStatus, in_check


class File(Base):
    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("user_id", "sha256", name="uq_files_user_sha256"),
        CheckConstraint(
            in_check("parse_status", [status.value for status in ParseStatus]),
            name="ck_files_parse_status",
        ),
        CheckConstraint(
            "parse_progress BETWEEN 0 AND 100", name="ck_files_parse_progress"
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
    parse_progress: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0")
    )
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    parse_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    @property
    def chunk_count(self) -> int:
        """解析结果里的切片数；未完成或脏数据一律按 0 处理。"""
        raw = (self.parse_result_json or {}).get("chunks")
        if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
            return raw
        return 0