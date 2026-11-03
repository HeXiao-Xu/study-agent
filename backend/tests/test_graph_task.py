"""S4-5 graph.build 任务：payload 校验、不 commit、结果字典。"""
from __future__ import annotations

import pytest

from app.services.graph_service import BuildSummary, TASK_BUILD_GRAPH
from app.tasks.build_graph import build_graph_task
from app.tasks.registry import get_handler


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self):
        self.commits += 1


def test_task_registered():
    assert get_handler(TASK_BUILD_GRAPH) is not None


def test_task_requires_subject_id():
    with pytest.raises(ValueError):
        build_graph_task(FakeSession(), {})


def test_task_returns_summary_and_does_not_commit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.tasks.build_graph.graph_service.build",
        lambda session, **kwargs: BuildSummary(
            subject_id=kwargs["subject_id"],
            nodes=108,
            created=107,
            updated=0,
            skipped_approved=0,
            skipped_rejected=0,
            calls=0,
            truncated=False,
            elapsed_ms=12,
        ),
    )
    session = FakeSession()
    result = build_graph_task(session, {"subject_id": 7, "relations": ["contains"]})
    assert result["created"] == 107
    assert result["subject_id"] == 7
    assert session.commits == 0


def test_task_passes_limit_and_relations(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    def fake_build(session, **kwargs):
        captured.update(kwargs)
        return BuildSummary(
            subject_id=kwargs["subject_id"],
            nodes=1,
            created=0,
            updated=0,
            skipped_approved=0,
            skipped_rejected=0,
            calls=0,
            truncated=False,
            elapsed_ms=1,
        )

    monkeypatch.setattr("app.tasks.build_graph.graph_service.build", fake_build)
    build_graph_task(
        FakeSession(), {"subject_id": 7, "relations": ["prerequisite"], "limit": 5}
    )
    assert captured["relations"] == ["prerequisite"]
    assert captured["limit"] == 5