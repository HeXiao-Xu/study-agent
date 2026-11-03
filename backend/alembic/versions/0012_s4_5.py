"""S4-5 知识图谱：knowledge_edges 审核三列 + llm_call_logs.scene 加 graph。"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_s4_5"
down_revision = "0011_s4_3"
branch_labels = None
depends_on = None

RELATION_CHECK = "review_status IN ('pending', 'approved', 'rejected')"
REVIEWED_CHECK = (
    "(review_status = 'pending' AND reviewed_at IS NULL) "
    "OR (review_status <> 'pending' AND reviewed_at IS NOT NULL)"
)
SCENE_CHECK = (
    "scene IN ('qa', 'query_rewrite', 'kp_align', 'embed', 'mistake', 'gen', "
    "'graph', 'agent')"
)


def upgrade() -> None:
    op.add_column(
        "knowledge_edges",
        sa.Column("review_status", sa.Text(), nullable=False, server_default="pending"),
    )
    op.add_column(
        "knowledge_edges", sa.Column("reviewed_by", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "knowledge_edges",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_knowledge_edges_reviewed_by",
        "knowledge_edges",
        "users",
        ["reviewed_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_knowledge_edges_review_status", "knowledge_edges", RELATION_CHECK
    )
    op.create_check_constraint(
        "ck_knowledge_edges_reviewed", "knowledge_edges", REVIEWED_CHECK
    )
    op.create_index(
        "ix_knowledge_edges_review_status", "knowledge_edges", ["review_status"]
    )
    # 历史边一律视为人工已通过，避免上线瞬间整图变成"待校验"
    op.execute(
        "UPDATE knowledge_edges SET review_status = 'approved', reviewed_at = now() "
        "WHERE review_status = 'pending'"
    )
    op.drop_constraint("ck_llm_call_logs_scene", "llm_call_logs", type_="check")
    op.create_check_constraint("ck_llm_call_logs_scene", "llm_call_logs", SCENE_CHECK)


def downgrade() -> None:
    op.drop_constraint("ck_llm_call_logs_scene", "llm_call_logs", type_="check")
    op.create_check_constraint(
        "ck_llm_call_logs_scene",
        "llm_call_logs",
        "scene IN ('qa', 'query_rewrite', 'kp_align', 'embed', 'mistake', 'gen', 'agent')",
    )
    op.drop_index("ix_knowledge_edges_review_status", table_name="knowledge_edges")
    op.drop_constraint("ck_knowledge_edges_reviewed", "knowledge_edges", type_="check")
    op.drop_constraint(
        "ck_knowledge_edges_review_status", "knowledge_edges", type_="check"
    )
    op.drop_constraint(
        "fk_knowledge_edges_reviewed_by", "knowledge_edges", type_="foreignkey"
    )
    op.drop_column("knowledge_edges", "reviewed_at")
    op.drop_column("knowledge_edges", "reviewed_by")
    op.drop_column("knowledge_edges", "review_status")