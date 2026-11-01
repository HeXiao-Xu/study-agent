"""S3-7 QA 结果缓存：key 规范化与 JSON 载荷校验。"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass

from app.core.cache import Cache
from app.core.config import get_settings
from app.schemas.qa import QaScopeIn

logger = logging.getLogger(__name__)

CACHE_VERSION = "qa:v1"


@dataclass(frozen=True)
class CachedCitation:
    index: int
    note_id: int
    chunk_id: int
    title: str | None
    heading_path: str | None
    page_no: int | None
    snippet: str
    score: float


@dataclass(frozen=True)
class CachedSuggestion:
    type: str
    text: str
    note_id: int | None = None


@dataclass(frozen=True)
class CachedAnswer:
    answer: str
    kind: str
    refused: bool
    refusal_reason: str | None
    suggestions: tuple[CachedSuggestion, ...]
    citations: tuple[CachedCitation, ...]
    prompt_version: str | None
    model: str | None


def normalize_question(question: str) -> str:
    return " ".join(question.split())


def _scope_json(scope: QaScopeIn | None) -> str:
    if scope is None:
        return "null"
    return json.dumps(
        scope.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def cache_key(user_id: int, question: str, scope: QaScopeIn | None) -> str:
    question_hash = hashlib.sha256(
        normalize_question(question).encode("utf-8")
    ).hexdigest()
    scope_hash = hashlib.sha256(_scope_json(scope).encode("utf-8")).hexdigest()[:16]
    return f"{CACHE_VERSION}:{user_id}:{scope_hash}:{question_hash}"


def _parse_citations(raw: object) -> tuple[CachedCitation, ...]:
    if not isinstance(raw, list):
        raise ValueError("citations 不是列表")
    citations: list[CachedCitation] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("citation 不是对象")
        citations.append(
            CachedCitation(
                index=int(item["index"]),
                note_id=int(item["note_id"]),
                chunk_id=int(item["chunk_id"]),
                title=item.get("title"),
                heading_path=item.get("heading_path"),
                page_no=(
                    int(item["page_no"]) if item.get("page_no") is not None else None
                ),
                snippet=str(item["snippet"]),
                score=float(item["score"]),
            )
        )
    return tuple(citations)


def _parse_suggestions(raw: object) -> tuple[CachedSuggestion, ...]:
    if not isinstance(raw, list):
        raise ValueError("suggestions 不是列表")
    suggestions: list[CachedSuggestion] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("suggestion 不是对象")
        note_id = item.get("note_id")
        suggestions.append(
            CachedSuggestion(
                type=str(item["type"]),
                text=str(item["text"]),
                note_id=int(note_id) if note_id is not None else None,
            )
        )
    return tuple(suggestions)


def _parse(raw: str) -> CachedAnswer:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("缓存载荷不是对象")
    kind = str(payload["kind"])
    if kind not in ("rag", "refused"):
        raise ValueError("kind 非法")
    return CachedAnswer(
        answer=str(payload["answer"]),
        kind=kind,
        refused=bool(payload["refused"]),
        refusal_reason=payload.get("refusal_reason"),
        suggestions=_parse_suggestions(payload["suggestions"]),
        citations=_parse_citations(payload["citations"]),
        prompt_version=payload.get("prompt_version"),
        model=payload.get("model"),
    )


def get(
    cache: Cache,
    *,
    user_id: int,
    question: str,
    scope: QaScopeIn | None,
) -> CachedAnswer | None:
    if not get_settings().qa_cache_enabled:
        return None
    key = cache_key(user_id, question, scope)
    raw = cache.get(key)
    if raw is None:
        return None
    try:
        return _parse(raw)
    except (ValueError, TypeError, KeyError):
        cache.delete(key)
        logger.warning("qa_cache_payload_invalid")
        return None


def put(
    cache: Cache,
    *,
    key: str,
    answer: str,
    kind: str,
    refused: bool,
    refusal_reason: str | None,
    suggestions: tuple[CachedSuggestion, ...],
    citations: tuple[CachedCitation, ...],
    prompt_version: str | None,
    model: str | None,
    ttl_seconds: int,
) -> bool:
    if not get_settings().qa_cache_enabled:
        return False
    payload = {
        "answer": answer,
        "kind": kind,
        "refused": refused,
        "refusal_reason": refusal_reason,
        "suggestions": [asdict(item) for item in suggestions],
        "citations": [asdict(item) for item in citations],
        "prompt_version": prompt_version,
        "model": model,
    }
    try:
        return cache.set(
            key,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ttl_seconds,
        )
    except (TypeError, ValueError):
        logger.warning("qa_cache_payload_encode_failed")
        return False