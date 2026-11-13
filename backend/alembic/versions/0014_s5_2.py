"""S5-2 组卷：papers 表（SCHEMA §6.1）。"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_s5_2"
down_revision = "0013_s4_7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "papers",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("constraint_json", postgresql.JSONB(), nullable=False),
        sa.Column("question_ids", postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("total_score", sa.Integer(), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="草稿"),
        sa.Column("generated_by", sa.Text(), nullable=False, server_default="manual"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("status IN ('草稿', '已生成', '已提交')", name="ck_papers_status"),
        sa.CheckConstraint(
            "generated_by IN ('manual', 'ai_agent')", name="ck_papers_generated_by"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_papers_user_id", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_papers_user_id", "papers", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_papers_user_id", table_name="papers")
    op.drop_table("papers")