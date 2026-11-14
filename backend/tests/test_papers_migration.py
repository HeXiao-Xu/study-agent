"""S5-2 papers 契约：列、CHECK、默认值、迁移链头。"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.enums import (
    PAPER_GENERATED_BY,
    PAPER_STATUSES,
    PaperGeneratedBy,
    PaperStatus,
    in_check,
)
from app.models.paper import Paper

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_paper_columns_match_schema():
    columns = set(Paper.__table__.columns.keys())
    assert columns == {
        "id",
        "user_id",
        "title",
        "constraint_json",
        "question_ids",
        "total_score",
        "duration_min",
        "status",
        "generated_by",
        "created_at",
    }


def test_status_values_and_check():
    assert PAPER_STATUSES == ("草稿", "已生成", "已提交")
    assert in_check("status", PaperStatus) == "status IN ('草稿', '已生成', '已提交')"


def test_generated_by_values_and_check():
    assert PAPER_GENERATED_BY == ("manual", "ai_agent")
    assert in_check("generated_by", PaperGeneratedBy) == (
        "generated_by IN ('manual', 'ai_agent')"
    )


def test_defaults_are_draft_and_manual():
    assert Paper.__table__.columns["status"].server_default.arg == "草稿"
    assert Paper.__table__.columns["generated_by"].server_default.arg == "manual"


def test_user_fk_cascades_and_is_indexed():
    column = Paper.__table__.columns["user_id"]
    assert {fk.target_fullname for fk in column.foreign_keys} == {"users.id"}
    index_names = {index.name for index in Paper.__table__.indexes}
    assert "ix_papers_user_id" in index_names


def test_migration_chain_head_is_s5_6():
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "0017_s5_6"