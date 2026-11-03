"""S4-4 变式题：触发、生成编排、入库（spec §6）。

三层：
- `enqueue_variants`：手动触发，先校验归属/诊断/题干，再建任务；
- `run_generation`：任务内用例，生成 → 逐题独立复算 → 比对 → 写 JSON，不 commit；
- `accept_variant`：把 JSON 里的一道题存进题库，回写 accepted 字段。

生成与复算是两次独立 LLM 调用（spec D-4）；比对在代码层做确定性判定（D-5）。
"""
from __future__ import annotations

import logging
import secrets
import time
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gen import (
    MAX_VARIANTS,
    PROMPT_VERSION,
    GenerationContext,
    GeneratedVariant,
    VariantGenerationError,
    VariantVerificationError,
    VerifyContext,
    generate_variants,
    match_answers,
    verify_answer,
)
from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.knowledge_point import KnowledgePoint
from app.models.mistake import Mistake
from app.models.mistake_analysis import MistakeAnalysis
from app.models.question import Question
from app.models.question_kp import QuestionKp
from app.models.user import User
from app.services import question_service

if TYPE_CHECKING:  # 顶层导入 app.tasks 会与「任务注册表 ↔ service 常量」互相循环（同 S4-3）
    from app.tasks.queue import TaskQueue

logger = logging.getLogger(__name__)

TASK_GENERATE_VARIANTS = "mistake.variants"
MAX_ROUNDS = 2
MAX_TOTAL_CALLS = 12
MIN_STEM_CHARS = 10
KP_LIMIT = 3
STEM_LIMIT = 2000
EXCERPT_LIMIT = 80


def _load_owned(
    session: Session, *, user_id: int, mistake_id: int
) -> tuple[Mistake, Question, MistakeAnalysis | None]:
    mistake = session.get(Mistake, mistake_id)
    if mistake is None or mistake.user_id != user_id:
        raise NotFoundError("错题不存在")
    question = session.get(Question, mistake.question_id)
    if question is None:
        raise NotFoundError("题目不存在")
    analysis = session.scalar(
        select(MistakeAnalysis).where(MistakeAnalysis.mistake_id == mistake_id)
    )
    return mistake, question, analysis


def _kp_names(session: Session, question_id: int) -> list[str]:
    stmt = (
        select(KnowledgePoint.name)
        .join(QuestionKp, QuestionKp.kp_id == KnowledgePoint.id)
        .where(QuestionKp.question_id == question_id)
        .order_by(QuestionKp.weight.desc(), KnowledgePoint.id)
        .limit(KP_LIMIT)
    )
    return [name for name in session.scalars(stmt).all() if name]


def _kp_links(session: Session, question_id: int) -> list[tuple[int, Decimal]]:
    """变式题继承原题的知识点链接（spec D-11）：不重新对齐，避免与例题不一致。"""
    stmt = (
        select(QuestionKp.kp_id, QuestionKp.weight)
        .where(QuestionKp.question_id == question_id)
        .order_by(QuestionKp.weight.desc(), QuestionKp.kp_id)
    )
    return [(row[0], row[1]) for row in session.execute(stmt).all()]


def build_generation_context(
    session: Session, *, question: Question, analysis: MistakeAnalysis | None
) -> GenerationContext:
    return GenerationContext(
        stem_md=question.stem_md[:STEM_LIMIT],
        options=[
            (item.get("key", ""), item.get("text", ""))
            for item in (question.options_json or [])
        ],
        correct_answer_md=question.answer_md,
        kp_names=_kp_names(session, question.id),
        cause_type=analysis.cause_type if analysis is not None else None,
        qtype=question.qtype,
        difficulty=question.difficulty,
        count=MAX_VARIANTS,
    )


def enqueue_variants(
    session: Session, *, owner: User, mistake_id: int, queue: TaskQueue
) -> Any:
    _mistake, question, analysis = _load_owned(
        session, user_id=owner.id, mistake_id=mistake_id
    )
    if analysis is None:
        raise ConflictError("请先完成错因诊断")
    if len((question.stem_md or "").strip()) < MIN_STEM_CHARS:
        raise ConflictError("这道题题干太短，暂不支持生成变式")
    from app.services import task_service  # 延迟导入，避免与 app.tasks 循环

    return task_service.create_task(
        session,
        owner=owner,
        name=TASK_GENERATE_VARIANTS,
        payload={"user_id": owner.id, "mistake_id": mistake_id},
        queue=queue,
    )


def _clamp_difficulty(original: int, value: int) -> int:
    """变式题难度锁在原题 ±1（spec D-7）；模型偶尔越界，这里收口，不因此弃题。"""
    low = max(1, original - 1)
    high = min(5, original + 1)
    return min(max(value, low), high)


def _item_payload(
    variant: GeneratedVariant,
    *,
    verified: str,
    kp_ids: list[int],
    attempts: int,
    original_difficulty: int,
) -> dict:
    return {
        "variant_id": secrets.token_hex(4),
        "stem_md": variant.stem_md,
        "options": [option.model_dump() for option in variant.options]
        if variant.options
        else None,
        "answer_md": variant.answer_md,
        "analysis_md": variant.analysis_md,
        "qtype": variant.qtype,
        "difficulty": _clamp_difficulty(original_difficulty, variant.difficulty),
        "kp_ids": kp_ids,
        "self_check": {
            "status": "passed",
            "attempts": attempts,
            "verified_answer_md": verified,
        },
        "accepted_question_id": None,
        "accepted_at": None,
    }


def run_generation(session: Session, *, user_id: int, mistake_id: int) -> dict[str, Any]:
    """一次生成用例：不 commit（由任务 runner 提交/回滚）。"""
    started = time.monotonic()
    _mistake, question, analysis = _load_owned(
        session, user_id=user_id, mistake_id=mistake_id
    )
    if analysis is None:
        raise NotFoundError("错题诊断不存在")
    base = build_generation_context(session, question=question, analysis=analysis)
    kp_ids = list(analysis.kp_ids or [])

    passed: list[dict] = []
    rejected: list[dict] = []
    rounds = 0
    calls = 0
    pending = MAX_VARIANTS
    while pending > 0 and rounds <= MAX_ROUNDS and calls < MAX_TOTAL_CALLS:
        rounds += 1
        try:
            variants = generate_variants(replace(base, count=pending))
            calls += 1
        except VariantGenerationError as exc:
            logger.warning(
                "variant_generate_failed mistake_id=%s rounds=%s error=%s",
                mistake_id,
                rounds,
                exc,
            )
            break
        failed: list[GeneratedVariant] = []
        for variant in variants:
            if calls >= MAX_TOTAL_CALLS:
                failed.append(variant)
                continue
            try:
                verified = verify_answer(
                    VerifyContext(
                        stem_md=variant.stem_md,
                        options=[
                            (option.key, option.text) for option in (variant.options or [])
                        ],
                    )
                )
                calls += 1
            except VariantVerificationError as exc:
                calls += 1
                logger.warning("variant_verify_failed mistake_id=%s error=%s", mistake_id, exc)
                rejected.append(
                    {"reason": "复算调用失败", "stem_excerpt": variant.stem_md[:EXCERPT_LIMIT]}
                )
                failed.append(variant)
                continue
            ok, reason = match_answers(variant.answer_md, verified)
            if ok:
                passed.append(
                    _item_payload(
                        variant,
                        verified=verified,
                        kp_ids=kp_ids,
                        attempts=rounds,
                        original_difficulty=base.difficulty,
                    )
                )
                continue
            logger.warning(
                "variant_self_check_rejected mistake_id=%s reason=%s stem_excerpt=%s",
                mistake_id,
                reason,
                variant.stem_md[:EXCERPT_LIMIT],
            )
            rejected.append({"reason": reason, "stem_excerpt": variant.stem_md[:EXCERPT_LIMIT]})
            failed.append(variant)
        pending = min(len(failed), MAX_VARIANTS - len(passed))

    payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": get_settings().llm_model,
        "prompt_version": PROMPT_VERSION,
        "stats": {
            "requested": MAX_VARIANTS,
            "passed": len(passed),
            "rejected": len(rejected),
            "rounds": rounds,
        },
        "items": passed,
        "rejected": rejected[:9],
    }
    analysis.similar_questions_json = payload
    session.flush()
    return {
        "mistake_id": mistake_id,
        "requested": MAX_VARIANTS,
        "passed": len(passed),
        "rejected": len(rejected),
        "rounds": rounds,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def accept_variant(
    session: Session, *, owner: User, mistake_id: int, variant_id: str
) -> tuple[Question, bool]:
    _mistake, question, analysis = _load_owned(
        session, user_id=owner.id, mistake_id=mistake_id
    )
    if analysis is None or not isinstance(analysis.similar_questions_json, dict):
        raise NotFoundError("变式题不存在或已被重新生成")
    payload = analysis.similar_questions_json
    items = [item for item in (payload.get("items") or []) if isinstance(item, dict)]
    target = next((item for item in items if item.get("variant_id") == variant_id), None)
    if target is None:
        raise NotFoundError("变式题不存在或已被重新生成")
    accepted_id = target.get("accepted_question_id")
    if accepted_id:
        existing = session.get(Question, int(accepted_id))
        if existing is not None:
            return existing, False
    created_question, created = question_service.create_generated_question(
        session,
        subject_id=question.subject_id,
        stem_md=str(target["stem_md"]),
        options_json=target.get("options"),
        answer_md=str(target["answer_md"]),
        analysis_md=target.get("analysis_md"),
        qtype=str(target["qtype"]),
        difficulty=int(target["difficulty"]),
        links=_kp_links(session, question.id),
        created_by=owner.id,
    )
    target["accepted_question_id"] = created_question.id
    target["accepted_at"] = datetime.now(timezone.utc).isoformat()
    # JSONB 默认不做脏检查，必须整体重新赋值才会写库
    analysis.similar_questions_json = {**payload, "items": items}
    session.commit()
    return created_question, created