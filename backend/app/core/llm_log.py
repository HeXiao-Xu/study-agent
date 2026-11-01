"""S3-7 调用日志写入口：best-effort 旁路，不影响主链路。"""
from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.context import get_current_user_id, get_trace_id
from app.core.db import new_session
from app.models.llm_call_log import LLMCallLog

logger = logging.getLogger(__name__)


def record_llm_call(
    *,
    scene: str,
    model: str,
    status: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cost_yuan: float | None,
    latency_ms: int | None,
    user_id: int | None = None,
    trace_id: str | None = None,
    session_factory: Callable[[], Session] = new_session,
) -> None:
    resolved_user_id = user_id if user_id is not None else get_current_user_id()
    resolved_trace_id = trace_id
    if resolved_trace_id is None:
        current_trace = get_trace_id()
        resolved_trace_id = None if current_trace == "-" else current_trace
    cost = None if cost_yuan is None else Decimal(str(round(cost_yuan, 8)))
    try:
        session = session_factory()
        try:
            session.add(
                LLMCallLog(
                    user_id=resolved_user_id,
                    scene=scene,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost=cost,
                    latency_ms=latency_ms,
                    trace_id=resolved_trace_id,
                    status=status,
                )
            )
            session.commit()
        finally:
            session.close()
    except Exception:
        logger.warning(
            "llm_call_log_failed",
            extra={"scene": scene, "status": status},
        )