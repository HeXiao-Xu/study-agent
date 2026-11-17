"""S6-2 Agent 状态机：agent_tasks / agent_steps 表。"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018_s6_2"
down_revision = "0017_s5_6"
branch_labels = None
depends_on = None

TASK_STATUS_CHECK = (
    "status IN ('pending', 'running', 'waiting_confirm', 'succeeded', 'failed')"
)
STEP_STATUS_CHECK = "status IN ('ok', 'error', 'waiting_confirm')"


def upgrade() -> None:
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("input_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("result_json", postgresql.JSONB(), nullable=True),
        sa.Column("state_json", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("steps_count", sa.Integer(), nullable=True),
        sa.Column("token_cost", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_agent_tasks_user_id"
        ),
        sa.CheckConstraint(TASK_STATUS_CHECK, name="ck_agent_tasks_status"),
    )
    op.create_index(
        "ix_agent_tasks_user_status", "agent_tasks", ["user_id", "status"]
    )
    op.create_table(
        "agent_steps",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("step_no", sa.Integer(), nullable=False),
        sa.Column("thought", sa.Text(), nullable=True),
        sa.Column("tool_name", sa.Text(), nullable=True),
        sa.Column("tool_input_json", postgresql.JSONB(), nullable=True),
        sa.Column("tool_output_json", postgresql.JSONB(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["agent_tasks.id"],
            name="fk_agent_steps_task_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(STEP_STATUS_CHECK, name="ck_agent_steps_status"),
        sa.UniqueConstraint("task_id", "step_no", name="uq_agent_steps_task_step"),
    )


def downgrade() -> None:
    op.drop_table("agent_steps")
    op.drop_table("agent_tasks")