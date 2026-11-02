"""S4-1 questions / question_kps 表

Revision ID: 0009_s4_1
Revises: 0008_s3_7
Create Date: 2026-11-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0009_s4_1"
down_revision = "0008_s3_7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "questions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("origin", sa.Text(), server_default=sa.text("'upload'"), nullable=False),
        sa.Column("source_file_id", sa.BigInteger(), nullable=True),
        sa.Column("stem_md", sa.Text(), nullable=False),
        sa.Column("stem_latex", sa.Text(), nullable=True),
        sa.Column("stem_hash", sa.Text(), nullable=False),
        sa.Column("options_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("answer_md", sa.Text(), nullable=True),
        sa.Column("analysis_md", sa.Text(), nullable=True),
        sa.Column("qtype", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.SmallInteger(), server_default=sa.text("3"), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "origin IN ('textbook', 'exam', 'mock', 'upload', 'ai')", name="ck_questions_origin"
        ),
        sa.CheckConstraint(
            "qtype IN ('单选', '多选', '填空', '解答')", name="ck_questions_qtype"
        ),
        sa.CheckConstraint("difficulty >= 1 AND difficulty <= 5", name="ck_questions_difficulty"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], name="fk_questions_subject_id"),
        sa.ForeignKeyConstraint(
            ["source_file_id"], ["files.id"], name="fk_questions_source_file_id"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_questions_created_by"),
        sa.PrimaryKeyConstraint("id", name="pk_questions"),
        sa.UniqueConstraint("subject_id", "stem_hash", name="uq_questions_subject_stem_hash"),
    )
    op.create_index("ix_questions_subject_id", "questions", ["subject_id"])
    op.create_index("ix_questions_origin", "questions", ["origin"])
    op.create_index("ix_questions_qtype", "questions", ["qtype"])
    op.create_index("ix_questions_tags", "questions", ["tags"], postgresql_using="gin")
    op.create_index(
        "ix_questions_embedding_hnsw",
        "questions",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )

    op.create_table(
        "question_kps",
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("kp_id", sa.BigInteger(), nullable=False),
        sa.Column("weight", sa.Numeric(8, 6), nullable=True),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["questions.id"],
            name="fk_question_kps_question_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["kp_id"],
            ["knowledge_points.id"],
            name="fk_question_kps_kp_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("question_id", "kp_id", name="pk_question_kps"),
    )
    op.create_index("ix_question_kps_kp_id", "question_kps", ["kp_id"])


def downgrade() -> None:
    op.drop_index("ix_question_kps_kp_id", table_name="question_kps")
    op.drop_table("question_kps")
    op.drop_index("ix_questions_embedding_hnsw", table_name="questions")
    op.drop_index("ix_questions_tags", table_name="questions")
    op.drop_index("ix_questions_qtype", table_name="questions")
    op.drop_index("ix_questions_origin", table_name="questions")
    op.drop_index("ix_questions_subject_id", table_name="questions")
    op.drop_table("questions")