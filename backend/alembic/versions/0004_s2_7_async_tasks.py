"""S2-7 异步任务状态表 async_tasks

Revision ID: 0004_s2_7
Revises: 0003_s2_5
Create Date: 2026-10-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_s2_7"
down_revision = "0003_s2_5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "async_tasks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_async_tasks_user_id"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_async_tasks_status",
        ),
    )
    op.create_index(
        "ix_async_tasks_user_id_created_at",
        "async_tasks",
        ["user_id", "created_at"],
    )
    op.create_index("ix_async_tasks_status", "async_tasks", ["status"])


def downgrade() -> None:
    op.drop_index("ix_async_tasks_status", table_name="async_tasks")
    op.drop_index("ix_async_tasks_user_id_created_at", table_name="async_tasks")
    op.drop_table("async_tasks")