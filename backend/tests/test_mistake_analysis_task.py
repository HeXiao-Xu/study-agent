"""S4-3 诊断任务：注册、skipped 短路、不 commit、错误透出。"""
from __future__ import annotations

import pytest

from app.services import mistake_analysis_service as svc
from app.tasks import registry
from app.tasks.analyze_mistake import run_analyze_mistake


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.flushed = 0

    def commit(self):
        self.commits += 1

    def flush(self):
        self.flushed += 1


def test_task_registered():
    assert "mistake.analyze" in registry.HANDLERS
    assert registry.get_handler("mistake.analyze") is run_analyze_mistake


def test_handler_returns_summary_and_does_not_commit(monkeypatch):
    monkeypatch.setattr(svc, "has_analysis", lambda *a, **k: False)
    analysis = type("A", (), {"id": 3})()
    monkeypatch.setattr(
        svc,
        "analyze",
        lambda session, *, user_id, mistake_id: (
            analysis,
            {
                "mistake_id": mistake_id,
                "cause_type": "概念不清",
                "secondary_causes": ["计算失误"],
                "confidence": 0.82,
                "retrieval_hits": 2,
            },
        ),
    )

    session = FakeSession()
    result = run_analyze_mistake(session, {"user_id": 1, "mistake_id": 12, "force": True})

    assert result["cause_type"] == "概念不清"
    assert result["retrieval_hits"] == 2
    assert session.commits == 0


def test_handler_skips_when_force_false_and_analysis_exists(monkeypatch):
    monkeypatch.setattr(svc, "has_analysis", lambda *a, **k: True)
    called: list[int] = []
    monkeypatch.setattr(svc, "analyze", lambda *a, **k: called.append(1))

    result = run_analyze_mistake(FakeSession(), {"user_id": 1, "mistake_id": 12, "force": False})

    assert result == {"mistake_id": 12, "skipped": True}
    assert called == []


def test_handler_runs_when_force_false_but_no_analysis(monkeypatch):
    monkeypatch.setattr(svc, "has_analysis", lambda *a, **k: False)
    monkeypatch.setattr(
        svc, "analyze", lambda session, *, user_id, mistake_id: (object(), {"mistake_id": mistake_id})
    )

    result = run_analyze_mistake(FakeSession(), {"user_id": 1, "mistake_id": 12, "force": False})

    assert result == {"mistake_id": 12}


def test_handler_propagates_analysis_error(monkeypatch):
    from app.ai.analyze import MistakeAnalysisError

    def boom(*_a, **_k):
        raise MistakeAnalysisError("诊断失败（已尝试 3 次）：bad json")

    monkeypatch.setattr(svc, "has_analysis", lambda *a, **k: False)
    monkeypatch.setattr(svc, "analyze", boom)

    with pytest.raises(MistakeAnalysisError):
        run_analyze_mistake(FakeSession(), {"user_id": 1, "mistake_id": 12, "force": True})


