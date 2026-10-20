"""S1-6 带引用回答与拒答。

流程：检索 → 阈值 → 上下文 → LLM → 引用校验 → 一次重试 → 拒答。
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.ai.embedding import EmbeddingClient
from app.ai.llm import (
    LLMClient,
    LLMMessage,
    LLMResponse,
    get_llm_client,
)
from app.ai.rag.prompt_builder import (
    Citation,
    ContextItem,
    build_context,
    render_prompt,
)
from app.ai.rag.retriever import RetrievalResult, retrieve_hybrid_reranked
from app.ai.rerank import RerankClient
from app.core.config import get_settings

logger = logging.getLogger(__name__)

REFUSAL_TEXT = "在你的笔记中没找到相关内容。可以换个问法，或先补充相关笔记。"
_CITATION_RE = re.compile(r"\[(\d+)\]")

RefusalReason = Literal[
    "no_context",
    "low_score",
    "citation_invalid",
    "empty_answer",
]


@dataclass(frozen=True)
class AnswerResult:
    answer: str
    refused: bool
    refusal_reason: RefusalReason | None
    citations: list[Citation]
    context_tokens: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    retrieval_ms: int
    llm_ms: int
    latency_ms: int
    cost_yuan: float
    llm_calls: int
    citation_retry_count: int
    degraded: bool
    top_rerank_score: float | None


def extract_citation_indices(answer: str) -> list[int]:
    return sorted({int(match.group(1)) for match in _CITATION_RE.finditer(answer)})


def validate_citations(
    answer: str,
    *,
    context_size: int,
) -> tuple[bool, list[int]]:
    indices = extract_citation_indices(answer)
    if not indices:
        return False, []
    if any(index < 1 or index > context_size for index in indices):
        return False, indices
    return True, indices


def _refused(
    reason: RefusalReason,
    *,
    retrieval_ms: int,
    context_tokens: int = 0,
    top_rerank_score: float | None = None,
    degraded: bool = False,
    llm_calls: int = 0,
    citation_retry_count: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    llm_ms: int = 0,
    cost_yuan: float = 0.0,
) -> AnswerResult:
    return AnswerResult(
        answer=REFUSAL_TEXT,
        refused=True,
        refusal_reason=reason,
        citations=[],
        context_tokens=context_tokens,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        retrieval_ms=retrieval_ms,
        llm_ms=llm_ms,
        latency_ms=retrieval_ms + llm_ms,
        cost_yuan=cost_yuan,
        llm_calls=llm_calls,
        citation_retry_count=citation_retry_count,
        degraded=degraded,
        top_rerank_score=top_rerank_score,
    )


def _cited(context_items: list[ContextItem], indices: list[int]) -> list[Citation]:
    return [context_items[index - 1].citation for index in indices]


def _call_llm(
    client: LLMClient,
    messages: list[LLMMessage],
    *,
    temperature: float,
    max_tokens: int,
) -> LLMResponse:
    return client.chat(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def answer_question(
    session: Session,
    question: str,
    *,
    user_id: int,
    top_k: int = 20,
    threshold: float | None = None,
    embedding_client: EmbeddingClient | None = None,
    rerank_client: RerankClient | None = None,
    llm_client: LLMClient | None = None,
) -> AnswerResult:
    if not question.strip():
        raise ValueError("question 不能为空")
    settings = get_settings()
    threshold_value = settings.qa_refuse_threshold if threshold is None else threshold
    if not 0.0 <= threshold_value <= 1.0:
        raise ValueError("threshold 必须在 [0, 1]")

    retrieval_started = time.perf_counter()
    retrieval: RetrievalResult = retrieve_hybrid_reranked(
        session,
        question,
        user_id=user_id,
        top_k=top_k,
        client=embedding_client,
        rerank_client=rerank_client,
    )
    retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)

    if not retrieval.reranked:
        return _refused("no_context", retrieval_ms=retrieval_ms)

    scores = [
        chunk.rerank_score
        for chunk in retrieval.reranked
        if chunk.rerank_score is not None
    ]
    top_score = max(scores) if scores else None
    degraded = bool(
        (retrieval.rerank_info and retrieval.rerank_info.fallback)
        or top_score is None
    )
    if not degraded and top_score is not None and top_score < threshold_value:
        return _refused(
            "low_score",
            retrieval_ms=retrieval_ms,
            top_rerank_score=top_score,
        )

    built = build_context(
        retrieval.reranked,
        max_tokens=settings.qa_context_max_tokens,
    )
    if not built.items:
        return _refused(
            "no_context",
            retrieval_ms=retrieval_ms,
            top_rerank_score=top_score,
            degraded=degraded,
        )

    prompt = render_prompt(built.text, question)
    client = llm_client if llm_client is not None else get_llm_client()
    messages = [LLMMessage(role="user", content=prompt)]
    first = _call_llm(
        client,
        messages,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_output_tokens,
    )
    llm_ms = first.latency_ms
    prompt_tokens = first.prompt_tokens
    completion_tokens = first.completion_tokens
    total_tokens = first.total_tokens
    cost_yuan = first.cost_yuan
    llm_calls = 1

    ok, indices = validate_citations(first.text, context_size=len(built.items))
    citation_retry_count = 0
    if ok:
        return AnswerResult(
            answer=first.text,
            refused=False,
            refusal_reason=None,
            citations=_cited(built.items, indices),
            context_tokens=built.tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            retrieval_ms=retrieval_ms,
            llm_ms=llm_ms,
            latency_ms=retrieval_ms + llm_ms,
            cost_yuan=cost_yuan,
            llm_calls=llm_calls,
            citation_retry_count=citation_retry_count,
            degraded=degraded,
            top_rerank_score=top_score,
        )

    if settings.qa_citation_max_retries < 1:
        return _refused(
            "citation_invalid",
            retrieval_ms=retrieval_ms,
            context_tokens=built.tokens,
            top_rerank_score=top_score,
            degraded=degraded,
            llm_calls=llm_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            llm_ms=llm_ms,
            cost_yuan=cost_yuan,
        )

    correction = (
        f"你上一次回答的引用编号不合法或缺失。本次可用的引用编号只有 "
        f"[1]..[{len(built.items)}]。请重写回答，只使用这些编号；"
        "如果资料不足，直接回答“你的资料里没有相关内容”。"
        "不要解释校验过程，不要使用不存在的编号。"
    )
    retry_messages = messages + [
        LLMMessage(role="assistant", content=first.text or "(空回答)"),
        LLMMessage(role="user", content=correction),
    ]
    second = _call_llm(
        client,
        retry_messages,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_output_tokens,
    )
    llm_ms += second.latency_ms
    prompt_tokens += second.prompt_tokens
    completion_tokens += second.completion_tokens
    total_tokens += second.total_tokens
    cost_yuan += second.cost_yuan
    llm_calls += 1
    citation_retry_count = 1

    ok, indices = validate_citations(second.text, context_size=len(built.items))
    if ok:
        return AnswerResult(
            answer=second.text,
            refused=False,
            refusal_reason=None,
            citations=_cited(built.items, indices),
            context_tokens=built.tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            retrieval_ms=retrieval_ms,
            llm_ms=llm_ms,
            latency_ms=retrieval_ms + llm_ms,
            cost_yuan=cost_yuan,
            llm_calls=llm_calls,
            citation_retry_count=citation_retry_count,
            degraded=degraded,
            top_rerank_score=top_score,
        )

    reason: RefusalReason = (
        "empty_answer" if not second.text.strip() else "citation_invalid"
    )
    return _refused(
        reason,
        retrieval_ms=retrieval_ms,
        context_tokens=built.tokens,
        top_rerank_score=top_score,
        degraded=degraded,
        llm_calls=llm_calls,
        citation_retry_count=citation_retry_count,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        llm_ms=llm_ms,
        cost_yuan=cost_yuan,
    )