"""S3-7 QA 缓存载荷：key 规范化、scope 隔离、损坏回退。"""
from __future__ import annotations

from datetime import date

from app.core.cache import MemoryCache
from app.schemas.qa import QaScopeIn
from app.services import qa_cache_service as qc


def _scope() -> QaScopeIn:
    return QaScopeIn(subject_id=7, folder="函数", start_date=date(2026, 1, 1))


def _answer() -> qc.CachedAnswer:
    return qc.CachedAnswer(
        answer="结论[1]",
        kind="rag",
        refused=False,
        refusal_reason=None,
        suggestions=(),
        citations=(
            qc.CachedCitation(
                index=1,
                note_id=55,
                chunk_id=101,
                title="数列笔记",
                heading_path="数列/错位相减法",
                page_no=2,
                snippet="错位相减法正文",
                score=0.9,
            ),
        ),
        prompt_version="qa/v1",
        model="qwen-plus",
    )


def test_cache_key_is_stable_and_scope_sensitive() -> None:
    assert qc.cache_key(18, "  错位相减  法 ", _scope()) == qc.cache_key(
        18, "错位相减 法", _scope()
    )
    assert qc.cache_key(18, "问题", _scope()) != qc.cache_key(18, "问题", None)
    assert qc.cache_key(18, "问题", _scope()) != qc.cache_key(19, "问题", _scope())


def test_put_then_get_roundtrip() -> None:
    cache = MemoryCache()
    key = qc.cache_key(18, "问题", _scope())
    assert (
        qc.put(
            cache,
            key=key,
            answer=_answer().answer,
            kind="rag",
            refused=False,
            refusal_reason=None,
            suggestions=(),
            citations=_answer().citations,
            prompt_version="qa/v1",
            model="qwen-plus",
            ttl_seconds=60,
        )
        is True
    )
    loaded = qc.get(cache, user_id=18, question="问题", scope=_scope())
    assert loaded == _answer()


def test_corrupt_payload_is_miss_and_deleted() -> None:
    cache = MemoryCache()
    key = qc.cache_key(18, "问题", _scope())
    cache.set(key, "{not-json", 60)
    assert qc.get(cache, user_id=18, question="问题", scope=_scope()) is None
    assert cache.get(key) is None