"""note_chunks ORM 模型：与 SCHEMA §4.3 一一对应（spec §5.1）。"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.core.db import Base


class NoteChunk(Base):
    __tablename__ = "note_chunks"
    __table_args__ = (
        UniqueConstraint("note_id", "chunk_index", name="uq_note_chunks_note_chunk_index"),
        Index("ix_note_chunks_user_id", "user_id"),
        Index("ix_note_chunks_tsv_gin", "tsv", postgresql_using="gin"),
        Index(
            "ix_note_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    note_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("notes.id", name="fk_note_chunks_note_id_notes", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_note_chunks_user_id_users"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str | None] = mapped_column(Text, nullable=True, server_default=text("'note'"))
    heading_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(1024), nullable=False)
    tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    source_file_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("files.id", name="fk_note_chunks_source_file_id_files"),
        nullable=True,
    )
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
