"""S4-7 掌握度：mastery 表（SCHEMA §6.3）。"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_s4_7"
down_revision = "0012_s4_5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mastery",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kp_id", sa.BigInteger(), nullable=False),
        sa.Column("mastery", sa.Numeric(4, 3), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_cnt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stability", sa.Numeric(6, 2), nullable=False, server_default="2"),
        sa.Column("last_practice_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_mastery_user_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["kp_id"],
            ["knowledge_points.id"],
            name="fk_mastery_kp_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "kp_id", name="uq_mastery_user_kp"),
    )
    op.create_index("ix_mastery_user_due", "mastery", ["user_id", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_mastery_user_due", table_name="mastery")
    op.drop_table("mastery")