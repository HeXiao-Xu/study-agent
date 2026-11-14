"""S5-5 review_items 契约：列、CHECK、唯一键、索引、迁移链头。"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Numeric

from app.models.review_item import ReviewItem

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_review_item_columns_match_schema():
    assert set(ReviewItem.__table__.columns.keys()) == {
        "id",
        "user_id",
        "kp_id",
        "ref_type",
        "ref_id",
        "due_at",
        "interval_days",
        "priority",
        "done_at",
    }


def test_review_item_constraints_and_unique():
    names = {constraint.name for constraint in ReviewItem.__table__.constraints}
    assert "uq_review_items_user_kp" in names
    assert "ck_review_items_ref_type" in names
    assert "ck_review_items_interval" in names
    assert "ck_review_items_priority" in names


def test_review_item_priority_precision():
    priority = ReviewItem.__table__.columns["priority"].type
    assert isinstance(priority, Numeric)
    assert (priority.precision, priority.scale) == (5, 4)


def test_review_item_foreign_keys_and_indexes():
    targets = {
        name: {fk.target_fullname for fk in column.foreign_keys}
        for name, column in ReviewItem.__table__.columns.items()
        if column.foreign_keys
    }
    assert targets == {
        "user_id": {"users.id"},
        "kp_id": {"knowledge_points.id"},
    }
    indexes = {index.name for index in ReviewItem.__table__.indexes}
    assert indexes == {
        "ix_review_items_user_due",
        "ix_review_items_user_done",
    }


def test_migration_chain_head_is_s5_6():
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "0017_s5_6"