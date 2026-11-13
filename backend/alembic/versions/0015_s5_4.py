"""S5-4 在线作答：answers 表（SCHEMA §6.2）。"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_s5_4"
down_revision = "0014_s5_2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "answers",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("paper_id", sa.BigInteger(), nullable=True),
        sa.Column("user_answer_md", sa.Text(), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("score", sa.Numeric(6, 2), nullable=True),
        sa.Column("self_rated", sa.Numeric(2, 1), nullable=True),
        sa.Column("time_spent_sec", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("score IS NULL OR score >= 0", name="ck_answers_score_nonneg"),
        sa.CheckConstraint(
            "self_rated IS NULL OR self_rated IN (0, 0.5, 1)",
            name="ck_answers_self_rated",
        ),
        sa.CheckConstraint(
            "time_spent_sec IS NULL OR time_spent_sec >= 0",
            name="ck_answers_time_nonneg",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_answers_user_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"], name="fk_answers_question_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], name="fk_answers_paper_id", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_answers_user_question", "answers", ["user_id", "question_id"])
    op.create_index("ix_answers_paper_id", "answers", ["paper_id"])
    op.create_index(
        "uq_answers_user_paper_question",
        "answers",
        ["user_id", "paper_id", "question_id"],
        unique=True,
        postgresql_where=sa.text("paper_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_answers_user_paper_question", table_name="answers")
    op.drop_index("ix_answers_paper_id", table_name="answers")
    op.drop_index("ix_answers_user_question", table_name="answers")
    op.drop_table("answers")