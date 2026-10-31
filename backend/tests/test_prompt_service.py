"""S3-4 Prompt 服务：FakeSession，不连库。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.ai.rag.prompt_builder import PromptTemplateError
from app.core.exceptions import (
    ConflictError,
    InvalidParamError,
    NotFoundError,
)
from app.models.prompt_template import PromptTemplate
from app.services import prompt_service


class FakeScalarResult:
    def __init__(self, items: list[object]) -> None:
        self._items = list(items)

    def all(self) -> list[object]:
        return list(self._items)

    def first(self) -> object | None:
        return self._items[0] if self._items else None


class FakeSession:
    def __init__(
        self,
        *,
        scalar_results: list[object] | None = None,
        scalars_results: list[list[object]] | None = None,
        get_results: dict[int, object] | None = None,
    ) -> None:
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.get_results = dict(get_results or {})
        self.added: list[object] = []
        self.commits = 0

    def scalar(self, statement: object) -> object | None:
        return self.scalar_results.pop(0)

    def scalars(self, statement: object) -> FakeScalarResult:
        return FakeScalarResult(self.scalars_results.pop(0))

    def get(self, entity: type, pk: int) -> object | None:
        return self.get_results.get(pk)

    def add(self, instance: object) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = 100 + len(self.added)  # type: ignore[attr-defined]
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, instance: object) -> None:
        return None


def _prompt(
    prompt_id: int,
    version: str,
    *,
    active: bool = False,
    name: str = "qa",
) -> PromptTemplate:
    now = datetime.now(timezone.utc)
    prompt = PromptTemplate(
        name=name,
        version=version,
        content="模板 {{ context }} {{ question }}",
        variables_json=["context", "question"],
        model_hint=None,
        is_active=active,
        created_by=1,
        created_at=now,
        updated_at=now,
    )
    prompt.id = prompt_id
    return prompt


def test_create_prompt_auto_version() -> None:
    session = FakeSession(
        scalar_results=[None],
        scalars_results=[["v1"]],
    )

    prompt = prompt_service.create_prompt_version(
        session,
        name="qa",
        content="新模板 {{ context }} {{ question }}",
        created_by=1,
    )

    assert prompt.version == "v2"
    assert prompt.is_active is False
    assert session.commits == 1


def test_create_prompt_explicit_version() -> None:
    session = FakeSession(
        scalar_results=[None],
        scalars_results=[["v1"]],
    )

    prompt = prompt_service.create_prompt_version(
        session,
        name="qa",
        content="模板",
        version="v9",
        created_by=1,
    )

    assert prompt.version == "v9"


def test_create_prompt_duplicate_version_conflict() -> None:
    session = FakeSession(scalar_results=[7])

    with pytest.raises(ConflictError):
        prompt_service.create_prompt_version(
            session,
            name="qa",
            content="模板",
            version="v1",
        )


def test_create_prompt_rejects_invalid_name() -> None:
    with pytest.raises(InvalidParamError):
        prompt_service.create_prompt_version(
            FakeSession(),
            name="QA Prompt",
            content="模板",
        )


def test_create_prompt_rejects_blank_content() -> None:
    with pytest.raises(InvalidParamError):
        prompt_service.create_prompt_version(
            FakeSession(),
            name="qa",
            content="   ",
        )


def test_create_prompt_with_activate_switches_old() -> None:
    old = _prompt(1, "v1", active=True)
    session = FakeSession(
        scalar_results=[None],
        scalars_results=[["v1"], [old]],
    )

    new = prompt_service.create_prompt_version(
        session,
        name="qa",
        content="v2 {{ context }} {{ question }}",
        activate=True,
        created_by=1,
    )

    assert old.is_active is False
    assert new.is_active is True
    assert session.commits == 1


def test_activate_prompt_unknown_raises() -> None:
    with pytest.raises(NotFoundError):
        prompt_service.activate_prompt(FakeSession(get_results={}), 99)


def test_activate_prompt_switches_exclusive() -> None:
    old = _prompt(1, "v1", active=True)
    target = _prompt(2, "v2", active=False)
    session = FakeSession(
        get_results={2: target},
        scalars_results=[[old, target]],
    )

    result = prompt_service.activate_prompt(session, 2)

    assert result is target
    assert target.is_active is True
    assert old.is_active is False
    assert session.commits == 1


def test_list_prompts_returns_rows() -> None:
    session = FakeSession(scalars_results=[[_prompt(2, "v2"), _prompt(1, "v1")]])

    rows = prompt_service.list_prompts(session, name="qa")

    assert [row.version for row in rows] == ["v2", "v1"]


def test_get_active_prompt_returns_active() -> None:
    active = _prompt(1, "v1", active=True)
    session = FakeSession(scalars_results=[[active]])

    assert prompt_service.get_active_prompt(session) is active


def test_get_active_prompt_missing_raises() -> None:
    with pytest.raises(PromptTemplateError):
        prompt_service.get_active_prompt(FakeSession(scalars_results=[[]]))


def test_create_prompt_records_author_and_variables() -> None:
    session = FakeSession(
        scalar_results=[None],
        scalars_results=[["v1"]],
    )

    prompt = prompt_service.create_prompt_version(
        session,
        name="qa",
        content="模板 {{ context }} {{ question }}",
        variables_json=["context", "question"],
        created_by=7,
    )

    assert prompt.created_by == 7
    assert prompt.variables_json == ["context", "question"]