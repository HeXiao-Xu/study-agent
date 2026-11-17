"""S6-2 `agent.run` ARQ handler：透传 service 状态。"""
from __future__ import annotations

import pytest

from app.services import agent_service
from app.tasks import agent_run


def test_agent_run_handler_returns_service_status(monkeypatch):
    monkeypatch.setattr(
        agent_service, "run_agent_task", lambda session, task_id: {"status": "succeeded"}
    )
    assert agent_run.agent_run_task(object(), {"agent_task_id": 7}) == {
        "status": "succeeded"
    }


def test_agent_run_handler_rejects_missing_id():
    with pytest.raises(ValueError):
        agent_run.agent_run_task(object(), {})