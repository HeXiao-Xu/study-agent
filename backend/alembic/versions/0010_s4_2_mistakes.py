"""S4-2 错题与错题诊断表

Revision ID: 0010_s4_2
Revises: 0009_s4_1
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_s4_2"
down_revision = "0009_s4_1"
branch_labels = None
depends_on = None

_STATUSES = ("待订正", "已订正", "已掌握")
_CAUSES = ("概念不清", "计算失误", "审题偏差", "方法不当", "知识遗忘", "时间不足", "unknown")


def upgrade() -> None:
    op.create_table(
        "mistakes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("my_answer_md", sa.Text(), nullable=True),
        sa.Column("correct_answer_md", sa.Text(), nullable=True),
        sa.Column("image_file_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'待订正'"), nullable=False),
        sa.Column("correct_streak", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_mistakes_user_id"),
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"], name="fk_mistakes_question_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["image_file_id"], ["files.id"], name="fk_mistakes_image_file_id", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("user_id", "question_id", name="uq_mistakes_user_question"),
        sa.CheckConstraint(
            "status IN ({})".format(", ".join(f"'{v}'" for v in _STATUSES)), name="ck_mistakes_status"
        ),
        sa.CheckConstraint("correct_streak >= 0", name="ck_mistakes_correct_streak"),
    )
    op.create_index("ix_mistakes_user_status", "mistakes", ["user_id", "status"])
    op.create_index("ix_mistakes_user_created", "mistakes", ["user_id", "created_at"])
    op.create_index("ix_mistakes_question_id", "mistakes", ["question_id"])

    op.create_table(
        "mistake_analyses",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("mistake_id", sa.BigInteger(), nullable=False),
        sa.Column("kp_ids", postgresql.ARRAY(sa.BigInteger()), nullable=True),
        sa.Column("cause_type", sa.Text(), nullable=False),
        sa.Column("error_step", sa.Text(), nullable=True),
        sa.Column("explanation_md", sa.Text(), nullable=True),
        sa.Column("similar_questions_json", postgresql.JSONB(), nullable=True),
        sa.Column("review_advice_md", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["mistake_id"], ["mistakes.id"], name="fk_mistake_analyses_mistake_id", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("mistake_id", name="uq_mistake_analyses_mistake_id"),
        sa.CheckConstraint(
            "cause_type IN ({})".format(", ".join(f"'{v}'" for v in _CAUSES)),
            name="ck_mistake_analyses_cause_type",
        ),
    )
    op.create_index(
        "ix_mistake_analyses_kp_ids", "mistake_analyses", ["kp_ids"], postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index("ix_mistake_analyses_kp_ids", table_name="mistake_analyses")
    op.drop_table("mistake_analyses")
    op.drop_index("ix_mistakes_question_id", table_name="mistakes")
    op.drop_index("ix_mistakes_user_created", table_name="mistakes")
    op.drop_index("ix_mistakes_user_status", table_name="mistakes")
    op.drop_table("mistakes")