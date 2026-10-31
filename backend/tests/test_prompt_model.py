"""S3-4 prompt_templates 模型契约（不连库）。"""
from __future__ import annotations

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.models.prompt_template import PromptTemplate


def test_prompt_template_columns_contract() -> None:
    table = PromptTemplate.__table__
    expected = {
        "id",
        "name",
        "version",
        "content",
        "variables_json",
        "model_hint",
        "is_active",
        "created_by",
        "created_at",
        "updated_at",
    }
    assert expected <= set(table.c.keys())
    assert table.c.id.primary_key is True
    assert table.c.name.nullable is False
    assert table.c.version.nullable is False
    assert table.c.content.nullable is False
    assert table.c.variables_json.nullable is True
    assert isinstance(table.c.variables_json.type, JSONB)
    assert table.c.model_hint.nullable is True
    assert table.c.is_active.nullable is False
    assert table.c.created_by.nullable is True
    assert table.c.created_at.nullable is False
    assert table.c.updated_at.nullable is False


def test_prompt_template_indexes_and_unique() -> None:
    table = PromptTemplate.__table__
    index_names = {index.name for index in table.indexes}
    assert "uq_prompt_templates_active_name" in index_names
    assert "ix_prompt_templates_name_created_at" in index_names
    unique_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_prompt_templates_name_version" in unique_names