"""S4-3 错题诊断增量列

Revision ID: 0011_s4_3
Revises: 0010_s4_2

给 mistake_analyses 增加「次因数组」与「LLM 自评置信度」，两者可空：
- secondary_causes：至多 2 个元素，必须落在 CauseType 值集内（<@ 包含判断）
- confidence：0.00–1.00，NUMERIC(3,2) 而非 float
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_s4_3"
down_revision = "0010_s4_2"
branch_labels = None
depends_on = None

_CAUSES = (
    "ARRAY['概念不清','计算失误','审题偏差','方法不当','知识遗忘','时间不足','unknown']::text[]"
)


def upgrade() -> None:
    op.add_column(
        "mistake_analyses",
        sa.Column("secondary_causes", postgresql.ARRAY(sa.Text()), nullable=True),
    )
    op.add_column(
        "mistake_analyses",
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
    )
    op.create_check_constraint(
        "ck_mistake_analyses_secondary_causes",
        "mistake_analyses",
        f"secondary_causes IS NULL OR secondary_causes <@ {_CAUSES}",
    )
    op.create_check_constraint(
        "ck_mistake_analyses_confidence",
        "mistake_analyses",
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_mistake_analyses_confidence", "mistake_analyses", type_="check")
    op.drop_constraint("ck_mistake_analyses_secondary_causes", "mistake_analyses", type_="check")
    op.drop_column("mistake_analyses", "confidence")
    op.drop_column("mistake_analyses", "secondary_causes")