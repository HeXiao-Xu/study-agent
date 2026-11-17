"""S6-2 `agent.run` ARQ handler。

service 在 handler 内延迟导入：`task_service` 在 import 链路里会先触发
`app.tasks.__init__`，顶层导入 `agent_service` 会形成循环。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.ai.agents.constants import TASK_RUN_AGENT
from app.tasks.registry import register


@register(TASK_RUN_AGENT)
def agent_run_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    task_id = int(payload.get("agent_task_id") or 0)
    if task_id <= 0:
        raise ValueError("payload 缺少 agent_task_id")
    from app.services import agent_service

    return agent_service.run_agent_task(session, task_id)