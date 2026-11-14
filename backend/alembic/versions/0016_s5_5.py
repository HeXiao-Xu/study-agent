"""S5-5 复习清单：review_items 表（SCHEMA §6.4）。"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_s5_5"
down_revision = "0015_s5_4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kp_id", sa.BigInteger(), nullable=False),
        sa.Column("ref_type", sa.Text(), nullable=False),
        sa.Column("ref_id", sa.BigInteger(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Numeric(5, 4), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "ref_type IN ('note', 'question', 'mistake')",
            name="ck_review_items_ref_type",
        ),
        sa.CheckConstraint(
            "interval_days >= 1 AND interval_days <= 30",
            name="ck_review_items_interval",
        ),
        sa.CheckConstraint(
            "priority IS NULL OR (priority >= 0 AND priority <= 1)",
            name="ck_review_items_priority",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_review_items_user_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["kp_id"],
            ["knowledge_points.id"],
            name="fk_review_items_kp_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "kp_id", name="uq_review_items_user_kp"),
    )
    op.create_index("ix_review_items_user_due", "review_items", ["user_id", "due_at"])
    op.create_index("ix_review_items_user_done", "review_items", ["user_id", "done_at"])


def downgrade() -> None:
    op.drop_index("ix_review_items_user_done", table_name="review_items")
    op.drop_index("ix_review_items_user_due", table_name="review_items")
    op.drop_table("review_items")