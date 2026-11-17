"""Agent 任务类型注册表；S6-3/S6-4 只需在这里追加实现。"""
from __future__ import annotations

from app.ai.agents.engine import AgentTaskSpec
from app.ai.agents.tasks.demo import DemoTaskSpec

TASK_SPECS: dict[str, type[AgentTaskSpec]] = {
    DemoTaskSpec.task_type: DemoTaskSpec,
}


def get_task_spec(task_type: str) -> type[AgentTaskSpec] | None:
    return TASK_SPECS.get(task_type)


__all__ = ["TASK_SPECS", "get_task_spec", "DemoTaskSpec"]