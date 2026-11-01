"""S3-7 llm_call_logs

Revision ID: 0008_s3_7
Revises: 0007_s3_5
Create Date: 2026-11-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_s3_7"
down_revision = "0007_s3_5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_call_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("scene", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("cost", sa.Numeric(14, 8), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scene IN ('qa', 'query_rewrite', 'kp_align', 'embed', "
            "'mistake', 'gen', 'agent')",
            name="ck_llm_call_logs_scene",
        ),
        sa.CheckConstraint(
            "status IN ('success', 'failed')",
            name="ck_llm_call_logs_status",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_llm_call_logs_user_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_llm_call_logs"),
    )
    op.create_index(
        "ix_llm_call_logs_user_id_created_at",
        "llm_call_logs",
        ["user_id", "created_at"],
    )
    op.create_index("ix_llm_call_logs_scene", "llm_call_logs", ["scene"])
    op.create_index("ix_llm_call_logs_trace_id", "llm_call_logs", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_call_logs_trace_id", table_name="llm_call_logs")
    op.drop_index("ix_llm_call_logs_scene", table_name="llm_call_logs")
    op.drop_index(
        "ix_llm_call_logs_user_id_created_at", table_name="llm_call_logs"
    )
    op.drop_table("llm_call_logs")