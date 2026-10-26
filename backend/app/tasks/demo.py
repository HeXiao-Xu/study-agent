"""验收/联调用的演示任务（S2-7）。"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.tasks.registry import register

TASK_DEMO_SLEEP = "demo.sleep"


@register(TASK_DEMO_SLEEP)
def demo_sleep(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    seconds = int(payload.get("seconds", 5))
    time.sleep(seconds)
    if payload.get("fail"):
        raise RuntimeError("演示任务按请求失败")
    return {"slept": seconds}