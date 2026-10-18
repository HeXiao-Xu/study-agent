"""S1-3 create note_chunks（首个迁移，只建这一张表）

Revision ID: 0001_s1_3
Revises:
Create Date: 2026-10-19

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0001_s1_3"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector 扩展必须先于 vector 列；IF NOT EXISTS 兼容 compose 首启已建的情况
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "note_chunks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("note_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("chunk_type", sa.Text(), server_default=sa.text("'note'"), nullable=True),
        sa.Column("heading_path", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("tsv", postgresql.TSVECTOR(), nullable=True),
        sa.Column("source_file_id", sa.BigInteger(), nullable=True),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column("bbox_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.UniqueConstraint("note_id", "chunk_index", name="uq_note_chunks_note_chunk_index"),
    )
    op.create_index("ix_note_chunks_user_id", "note_chunks", ["user_id"])
    op.create_index("ix_note_chunks_tsv_gin", "note_chunks", ["tsv"], postgresql_using="gin")
    op.create_index(
        "ix_note_chunks_embedding_hnsw",
        "note_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )


def downgrade() -> None:
    op.drop_table("note_chunks")
