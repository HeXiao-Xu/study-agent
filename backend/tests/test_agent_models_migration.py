"""S6-2 agent_tasks/agent_steps 契约：列、CHECK、唯一键、FK、索引、迁移头。"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.agent_step import AgentStep
from app.models.agent_task import AgentTask

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_agent_task_columns_match_schema():
    assert set(AgentTask.__table__.columns.keys()) == {
        "id",
        "user_id",
        "task_type",
        "input_json",
        "status",
        "result_json",
        "state_json",
        "error",
        "steps_count",
        "token_cost",
        "started_at",
        "finished_at",
        "created_at",
    }


def test_agent_step_columns_match_schema():
    assert set(AgentStep.__table__.columns.keys()) == {
        "id",
        "task_id",
        "step_no",
        "thought",
        "tool_name",
        "tool_input_json",
        "tool_output_json",
        "latency_ms",
        "status",
    }


def test_agent_constraints_fk_and_indexes():
    task_constraints = {c.name for c in AgentTask.__table__.constraints}
    assert "ck_agent_tasks_status" in task_constraints
    assert "fk_agent_tasks_user_id" in task_constraints
    step_constraints = {c.name for c in AgentStep.__table__.constraints}
    assert "ck_agent_steps_status" in step_constraints
    assert "uq_agent_steps_task_step" in step_constraints
    fk = next(iter(AgentStep.__table__.columns["task_id"].foreign_keys))
    assert fk.target_fullname == "agent_tasks.id"
    assert fk.ondelete == "CASCADE"
    assert {i.name for i in AgentTask.__table__.indexes} == {"ix_agent_tasks_user_status"}


def test_migration_chain_head_is_s6_2():
    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    assert script.get_current_head() == "0018_s6_2"