"""S3-3 查询改写服务：历史裁剪 + 进程内 LRU/TTL 缓存 + 失败降级。

LLM/Prompt/JSON 校验在 ai/rag/query_rewriter.py；本层不写 Prompt、不直接调 httpx。
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, replace

from app.ai.llm import LLMClient
from app.ai.llm.errors import LLMError
from app.ai.rag.query_rewriter import (
    REWRITE_PROMPT_VERSION,
    HistoryTurn,
    Intent,
    RewriteError,
    rewrite_with_llm,
)
from app.core.config import get_settings

logger = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 500
FALLBACK_REPLY = "我可以帮你查笔记、找题或解释概念。"


@dataclass(frozen=True)
class RewriteResult:
    intent: Intent
    rewritten_query: str
    reply: str | None
    is_followup: bool
    degraded: bool
    cache_hit: bool
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_yuan: float
    latency_ms: int
    error: str | None


@dataclass(frozen=True)
class _CacheEntry:
    created_at: float
    result: RewriteResult


_CACHE: OrderedDict[str, _CacheEntry] = OrderedDict()
_CACHE_LOCK = threading.Lock()


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _trim_history(
    history: list[HistoryTurn],
    *,
    turns: int,
    chars: int,
) -> list[HistoryTurn]:
    if not history:
        return []
    user_positions = [index for index, turn in enumerate(history) if turn.role == "user"]
    start = user_positions[-turns] if len(user_positions) > turns else 0
    trimmed: list[HistoryTurn] = []
    for turn in history[start:]:
        content = " ".join(turn.content.split())[:chars]
        trimmed.append(HistoryTurn(role=turn.role, content=content))
    return trimmed


def _cache_key(question: str, history: list[HistoryTurn], model: str) -> str:
    parts = [REWRITE_PROMPT_VERSION, model, question]
    parts.extend(f"{turn.role}:{turn.content}" for turn in history)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _cache_get(key: str, *, ttl: int, now: float) -> RewriteResult | None:
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            return None
        if now - entry.created_at >= ttl:
            _CACHE.pop(key, None)
            return None
        _CACHE.move_to_end(key)
        return entry.result


def _cache_put(key: str, result: RewriteResult, *, size: int, now: float) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = _CacheEntry(created_at=now, result=result)
        _CACHE.move_to_end(key)
        while len(_CACHE) > size:
            _CACHE.popitem(last=False)


def _fallback(
    question: str,
    *,
    history: list[HistoryTurn],
    error: Exception,
    started: float,
) -> RewriteResult:
    return RewriteResult(
        intent="note_query",
        rewritten_query=question,
        reply=FALLBACK_REPLY,
        is_followup=bool(history),
        degraded=True,
        cache_hit=False,
        llm_calls=getattr(error, "llm_calls", 0),
        prompt_tokens=getattr(error, "prompt_tokens", 0),
        completion_tokens=getattr(error, "completion_tokens", 0),
        total_tokens=getattr(error, "total_tokens", 0),
        cost_yuan=getattr(error, "cost_yuan", 0.0),
        latency_ms=int((time.perf_counter() - started) * 1000),
        error=type(error).__name__,
    )


def _log(result: RewriteResult) -> None:
    logger.info(
        "query_rewrite_done",
        extra={
            "scene": "query_rewrite",
            "intent": result.intent,
            "is_followup": result.is_followup,
            "degraded": result.degraded,
            "cache_hit": result.cache_hit,
            "llm_calls": result.llm_calls,
            "latency_ms": result.latency_ms,
            "total_tokens": result.total_tokens,
            "cost_yuan": round(result.cost_yuan, 8),
        },
    )


def rewrite_query(
    question: str,
    *,
    history: list[HistoryTurn] | None = None,
    use_cache: bool = True,
    llm_client: LLMClient | None = None,
) -> RewriteResult:
    started = time.perf_counter()
    clean = question.strip()
    if not clean:
        raise ValueError("question 不能为空")
    if len(clean) > MAX_QUESTION_CHARS:
        raise ValueError(f"question 过长（最多 {MAX_QUESTION_CHARS} 字）")

    settings = get_settings()
    trimmed = _trim_history(
        history or [],
        turns=settings.query_rewrite_max_history_turns,
        chars=settings.query_rewrite_history_content_chars,
    )

    if not settings.query_rewrite_enabled:
        result = RewriteResult(
            intent="note_query",
            rewritten_query=clean,
            reply=None,
            is_followup=bool(trimmed),
            degraded=False,
            cache_hit=False,
            llm_calls=0,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost_yuan=0.0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=None,
        )
        _log(result)
        return result

    key = _cache_key(clean, trimmed, settings.llm_model)
    if use_cache:
        cached = _cache_get(
            key,
            ttl=settings.query_rewrite_cache_ttl_seconds,
            now=time.monotonic(),
        )
        if cached is not None:
            result = replace(
                cached,
                cache_hit=True,
                llm_calls=0,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                cost_yuan=0.0,
                latency_ms=0,
            )
            _log(result)
            return result

    try:
        call = rewrite_with_llm(
            clean,
            history=trimmed,
            llm_client=llm_client,
            max_tokens=settings.query_rewrite_max_tokens,
        )
        result = RewriteResult(
            intent=call.output.intent,
            rewritten_query=call.output.rewritten_query.strip(),
            reply=call.output.reply.strip() or None,
            is_followup=call.output.is_followup,
            degraded=False,
            cache_hit=False,
            llm_calls=call.llm_calls,
            prompt_tokens=call.prompt_tokens,
            completion_tokens=call.completion_tokens,
            total_tokens=call.total_tokens,
            cost_yuan=call.cost_yuan,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=None,
        )
    except (LLMError, RewriteError) as exc:
        result = _fallback(clean, history=trimmed, error=exc, started=started)
    else:
        if use_cache:
            _cache_put(
                key,
                result,
                size=settings.query_rewrite_cache_size,
                now=time.monotonic(),
            )

    _log(result)
    return result