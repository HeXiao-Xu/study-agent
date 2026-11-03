"""S4-3 错因诊断任务：handler 不 commit，由 runner 统一提交/回滚。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services import mistake_analysis_service
from app.services.mistake_analysis_service import TASK_ANALYZE_MISTAKE
from app.tasks.registry import register


@register(TASK_ANALYZE_MISTAKE)
def run_analyze_mistake(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    user_id = int(payload["user_id"])
    mistake_id = int(payload["mistake_id"])
    # force=false 且已有诊断：不重复花 LLM 调用，直接回 skipped 让前端收尾
    if not payload.get("force", True) and mistake_analysis_service.has_analysis(
        session, mistake_id
    ):
        return {"mistake_id": mistake_id, "skipped": True}
    _analysis, summary = mistake_analysis_service.analyze(
        session, user_id=user_id, mistake_id=mistake_id
    )
    return summary