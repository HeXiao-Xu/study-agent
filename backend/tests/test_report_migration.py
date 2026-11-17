"""S5-6 report scene 契约：枚举、CHECK、迁移链头。"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.enums import LLMCallScene, in_check
from app.models.llm_call_log import LLMCallLog

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_llm_call_scene_has_report():
    assert LLMCallScene.REPORT.value == "report"
    assert "report" in in_check("scene", LLMCallScene)


def test_llm_call_log_check_includes_report():
    constraint = next(
        item
        for item in LLMCallLog.__table__.constraints
        if item.name == "ck_llm_call_logs_scene"
    )
    assert "report" in str(constraint.sqltext)


def test_migration_chain_head_is_s5_6():
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "0018_s6_2"