"""S4-5 知识图谱构建任务（同步 handler，不自行 commit）。"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import Session

from app.services import graph_service
from app.services.graph_service import TASK_BUILD_GRAPH
from app.tasks.registry import register

logger = logging.getLogger(__name__)


@register(TASK_BUILD_GRAPH)
def build_graph_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    subject_id = int(payload.get("subject_id") or 0)
    if subject_id <= 0:
        raise ValueError("payload 缺少 subject_id")
    relations = payload.get("relations")
    limit = payload.get("limit")
    summary = graph_service.build(
        session,
        subject_id=subject_id,
        relations=list(relations) if relations else None,
        limit=int(limit) if limit else None,
    )
    result = asdict(summary)
    logger.info(
        "graph_build_task_done",
        extra={
            "subject_id": subject_id,
            "nodes": summary.nodes,
            # 不用 created/updated 作键：与 LogRecord 自带属性冲突
            "created_edges": summary.created,
            "updated_edges": summary.updated,
            "calls": summary.calls,
            "truncated": summary.truncated,
        },
    )
    return result