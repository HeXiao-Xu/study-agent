"""S4-4 变式题生成任务：handler 不 commit，由 runner 统一提交/回滚。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services import question_gen_service
from app.services.question_gen_service import TASK_GENERATE_VARIANTS
from app.tasks.registry import register


@register(TASK_GENERATE_VARIANTS)
def run_generate_variants(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    return question_gen_service.run_generation(
        session,
        user_id=int(payload["user_id"]),
        mistake_id=int(payload["mistake_id"]),
    )