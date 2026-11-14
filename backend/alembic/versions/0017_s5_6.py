"""S5-6 学习报告：llm_call_logs.scene 增加 report。"""
from __future__ import annotations

from alembic import op

revision = "0017_s5_6"
down_revision = "0016_s5_5"
branch_labels = None
depends_on = None

SCENE_CHECK = (
    "scene IN ('qa', 'query_rewrite', 'kp_align', 'embed', 'mistake', 'gen', "
    "'graph', 'agent', 'report')"
)
OLD_SCENE_CHECK = (
    "scene IN ('qa', 'query_rewrite', 'kp_align', 'embed', 'mistake', 'gen', "
    "'graph', 'agent')"
)


def upgrade() -> None:
    op.drop_constraint("ck_llm_call_logs_scene", "llm_call_logs", type_="check")
    op.create_check_constraint("ck_llm_call_logs_scene", "llm_call_logs", SCENE_CHECK)


def downgrade() -> None:
    op.drop_constraint("ck_llm_call_logs_scene", "llm_call_logs", type_="check")
    op.create_check_constraint("ck_llm_call_logs_scene", "llm_call_logs", OLD_SCENE_CHECK)