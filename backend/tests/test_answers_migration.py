"""S5-4 answers 契约：列、CHECK、部分唯一索引、迁移链头。"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Numeric

from app.models.answer import Answer

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_answer_columns_match_schema():
    assert set(Answer.__table__.columns.keys()) == {
        "id",
        "user_id",
        "question_id",
        "paper_id",
        "user_answer_md",
        "is_correct",
        "score",
        "self_rated",
        "time_spent_sec",
        "created_at",
    }


def test_score_and_self_rated_precision():
    score = Answer.__table__.columns["score"].type
    rated = Answer.__table__.columns["self_rated"].type
    assert isinstance(score, Numeric) and (score.precision, score.scale) == (6, 2)
    assert isinstance(rated, Numeric) and (rated.precision, rated.scale) == (2, 1)


def test_foreign_keys_and_indexes():
    targets = {
        name: {fk.target_fullname for fk in column.foreign_keys}
        for name, column in Answer.__table__.columns.items()
        if column.foreign_keys
    }
    assert targets == {
        "user_id": {"users.id"},
        "question_id": {"questions.id"},
        "paper_id": {"papers.id"},
    }
    indexes = {index.name: index for index in Answer.__table__.indexes}
    assert "ix_answers_user_question" in indexes
    assert "ix_answers_paper_id" in indexes
    partial = indexes["uq_answers_user_paper_question"]
    assert partial.unique is True
    assert str(partial.dialect_options["postgresql"]["where"]) == "paper_id IS NOT NULL"


def test_checks_present():
    names = {constraint.name for constraint in Answer.__table__.constraints}
    assert {"ck_answers_score_nonneg", "ck_answers_self_rated", "ck_answers_time_nonneg"} <= names


def test_migration_chain_head_is_s5_6():
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "0017_s5_6"