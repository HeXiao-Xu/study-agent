"""S3-7 llm_call_logs 模型契约：枚举、字段、约束与索引。"""
from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Numeric, Text

from app.models import LLMCallLog
from app.models.enums import LLMCallScene, LLMCallStatus, in_check


def test_llm_call_scene_and_status_values_match_schema() -> None:
    assert {item.value for item in LLMCallScene} == {
        "qa",
        "query_rewrite",
        "kp_align",
        "embed",
        "mistake",
        "gen",
        "agent",
    }
    assert {item.value for item in LLMCallStatus} == {"success", "failed"}


def test_llm_call_log_columns_match_schema() -> None:
    columns = {column.name for column in LLMCallLog.__table__.columns}
    assert columns == {
        "id",
        "user_id",
        "scene",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "cost",
        "latency_ms",
        "trace_id",
        "status",
        "created_at",
    }
    assert isinstance(LLMCallLog.__table__.c.id.type, BigInteger)
    assert isinstance(LLMCallLog.__table__.c.cost.type, Numeric)
    assert isinstance(LLMCallLog.__table__.c.model.type, Text)
    assert isinstance(LLMCallLog.__table__.c.created_at.type, DateTime)


def test_llm_call_log_constraints_and_indexes_exist() -> None:
    constraints = {
        item.name
        for item in LLMCallLog.__table__.constraints
        if isinstance(item, CheckConstraint)
    }
    assert constraints == {"ck_llm_call_logs_scene", "ck_llm_call_logs_status"}
    indexes = {
        item.name for item in LLMCallLog.__table__.indexes if isinstance(item, Index)
    }
    assert indexes == {
        "ix_llm_call_logs_user_id_created_at",
        "ix_llm_call_logs_scene",
        "ix_llm_call_logs_trace_id",
    }


def test_llm_call_log_check_text_is_rendered() -> None:
    assert in_check("scene", LLMCallScene) == (
        "scene IN ('qa', 'query_rewrite', 'kp_align', 'embed', "
        "'mistake', 'gen', 'agent')"
    )