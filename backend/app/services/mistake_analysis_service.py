"""错因诊断的触发与执行（S4-3）。

分层：
- `enqueue_analysis` / `safe_enqueue`：任务提交（先校验归属，再落 async_tasks 并入队）；
- `build_context`：把题、错题、知识点、笔记拼成 `DiagnosisContext`（笔记检索可降级）；
- `analyze`：任务内执行的一次用例，upsert 诊断行，不 commit。

一个错题至多一条诊断（`uq_mistake_analyses_mistake_id`），重跑走 UPDATE 覆盖，
并把 `created_at` 刷新为最近一次诊断时间（spec D-3）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.analyze import PROMPT_VERSION, DiagnosisContext, analyze_mistake
from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.models.async_task import AsyncTask
from app.models.knowledge_point import KnowledgePoint
from app.models.mistake import Mistake
from app.models.mistake_analysis import MistakeAnalysis
from app.models.question import Question
from app.models.question_kp import QuestionKp
from app.models.user import User
from app.services import retrieval_service

if TYPE_CHECKING:  # 顶层导入 app.tasks 会让「任务注册表 ↔ service 常量」互相循环（同 S3-1）
    from app.tasks.queue import TaskQueue

logger = logging.getLogger(__name__)

TASK_ANALYZE_MISTAKE = "mistake.analyze"
MAX_KP = 3
MAX_PREREQ = 5
NOTE_TOP_K = 3
NOTE_QUERY_LIMIT = 200


def has_analysis(session: Session, mistake_id: int) -> bool:
    stmt = select(MistakeAnalysis.id).where(MistakeAnalysis.mistake_id == mistake_id).limit(1)
    return session.scalar(stmt) is not None


def _ensure_owned(session: Session, *, user_id: int, mistake_id: int) -> None:
    row = session.scalar(
        select(Mistake.id).where(Mistake.id == mistake_id, Mistake.user_id == user_id)
    )
    if row is None:
        raise NotFoundError("错题不存在")


def enqueue_analysis(
    session: Session,
    *,
    owner: User,
    mistake_id: int,
    queue: TaskQueue,
    force: bool = False,
    skip_if_analyzed: bool = True,
) -> AsyncTask | None:
    """建诊断任务；自动触发时已有诊断直接跳过（返回 None），手动接口一定建任务。"""
    _ensure_owned(session, user_id=owner.id, mistake_id=mistake_id)
    if skip_if_analyzed and has_analysis(session, mistake_id):
        return None
    # 延迟导入：app.tasks 包会 import 本模块，顶层导入 task_service 会循环（同 S3-1 index_service）
    from app.services import task_service

    return task_service.create_task(
        session,
        owner=owner,
        name=TASK_ANALYZE_MISTAKE,
        payload={"user_id": owner.id, "mistake_id": mistake_id, "force": force},
        queue=queue,
    )


def safe_enqueue(session: Session, *, owner: User, mistake_id: int, queue: TaskQueue) -> bool:
    """best-effort：入队失败只记 WARNING，不影响录入/识别主流程。"""
    try:
        enqueue_analysis(session, owner=owner, mistake_id=mistake_id, queue=queue)
    except Exception as exc:  # noqa: BLE001 - 入队失败不该阻断业务
        logger.warning("mistake_analyze_enqueue_failed mistake_id=%s error=%s", mistake_id, exc)
        return False
    return True


def _kp_rows(session: Session, question_id: int) -> list[tuple[int, str, Decimal | None]]:
    stmt = (
        select(KnowledgePoint.id, KnowledgePoint.name, QuestionKp.weight)
        .join(QuestionKp, QuestionKp.kp_id == KnowledgePoint.id)
        .where(QuestionKp.question_id == question_id)
        .order_by(QuestionKp.weight.desc(), KnowledgePoint.id)
        .limit(MAX_KP)
    )
    return list(session.execute(stmt).all())


def _prerequisite_names(session: Session, kp_ids: list[int]) -> list[str]:
    """前置知识近似：这批 KP 的父节点名称（图谱 S4-5 之前的最优近似）。"""
    if not kp_ids:
        return []
    parent_ids = (
        select(KnowledgePoint.parent_id)
        .where(KnowledgePoint.id.in_(kp_ids), KnowledgePoint.parent_id.is_not(None))
        .scalar_subquery()
    )
    stmt = (
        select(KnowledgePoint.name)
        .where(KnowledgePoint.id.in_(parent_ids))
        .order_by(KnowledgePoint.id)
        .limit(MAX_PREREQ)
    )
    return [name for name in session.scalars(stmt).all() if name]


def _note_snippets(session: Session, *, user_id: int, query: str) -> list[tuple[str, str]]:
    """笔记片段；检索不可用只降级为空，不阻断诊断（spec D-7）。"""
    try:
        response = retrieval_service.search_chunks(
            session, user_id=user_id, query=query[:NOTE_QUERY_LIMIT], top_k=NOTE_TOP_K
        )
    except Exception as exc:  # noqa: BLE001 - 检索失败只降级
        logger.warning("mistake_analyze_retrieval_failed error=%s", exc)
        return []
    return [((hit.note_title or "笔记"), hit.snippet) for hit in response.hits]


def build_context(
    session: Session, *, user_id: int, mistake: Mistake, question: Question
) -> DiagnosisContext:
    rows = _kp_rows(session, question.id)
    return DiagnosisContext(
        stem_md=question.stem_md,
        options=[
            (item.get("key", ""), item.get("text", "")) for item in (question.options_json or [])
        ],
        correct_answer_md=mistake.correct_answer_md or question.answer_md,
        my_answer_md=mistake.my_answer_md,
        kp_names=[row[1] for row in rows],
        prerequisite_names=_prerequisite_names(session, [row[0] for row in rows]),
        notes=_note_snippets(session, user_id=user_id, query=question.stem_md),
    )


def analyze(
    session: Session, *, user_id: int, mistake_id: int
) -> tuple[MistakeAnalysis, dict[str, Any]]:
    """一次诊断用例：不 commit（由任务 runner 提交/回滚）。"""
    mistake = session.get(Mistake, mistake_id)
    if mistake is None or mistake.user_id != user_id:
        raise NotFoundError("错题不存在")
    question = session.get(Question, mistake.question_id)
    if question is None:
        raise NotFoundError("题目不存在")

    context = build_context(session, user_id=user_id, mistake=mistake, question=question)
    result = analyze_mistake(context)

    analysis = session.scalar(
        select(MistakeAnalysis).where(MistakeAnalysis.mistake_id == mistake_id)
    )
    if analysis is None:
        analysis = MistakeAnalysis(
            mistake_id=mistake_id,
            cause_type=result.cause_type.value,
            model=get_settings().llm_model,
            prompt_version=PROMPT_VERSION,
        )
        session.add(analysis)
    analysis.cause_type = result.cause_type.value
    analysis.secondary_causes = [cause.value for cause in result.secondary_causes]
    analysis.error_step = result.error_step
    analysis.explanation_md = result.explanation_md
    analysis.review_advice_md = result.review_advice_md
    analysis.confidence = Decimal(str(round(result.confidence, 2)))
    analysis.kp_ids = [row[0] for row in _kp_rows(session, question.id)]
    analysis.model = get_settings().llm_model
    analysis.prompt_version = PROMPT_VERSION
    # server_default 只在 INSERT 生效；重跑要表达「最近一次诊断」，必须显式刷新
    analysis.created_at = datetime.now(timezone.utc)
    session.flush()

    summary = {
        "mistake_id": mistake_id,
        "cause_type": analysis.cause_type,
        "secondary_causes": list(analysis.secondary_causes or []),
        "confidence": float(analysis.confidence) if analysis.confidence is not None else None,
        "retrieval_hits": len(context.notes),
    }
    return analysis, summary