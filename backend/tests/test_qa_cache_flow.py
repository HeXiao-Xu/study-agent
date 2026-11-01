"""S3-7 QA 缓存命中分支：prepare 提前返回、stream 零 token、miss 后写缓存。"""
from __future__ import annotations

from dataclasses import replace

from app.ai.rag.answerer import AnswerChunk
from app.core.cache import MemoryCache
from app.services import qa_cache_service, qa_service
from app.services.qa_cache_service import CachedAnswer, CachedCitation, CachedSuggestion


def _cache_answer() -> CachedAnswer:
    return CachedAnswer(
        answer="缓存回答[1]",
        kind="rag",
        refused=False,
        refusal_reason=None,
        suggestions=(),
        citations=(
            CachedCitation(
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
        prompt_version="qa/v2",
        model="qwen-plus",
    )


def _put(cache, key: str, answer: CachedAnswer) -> None:
    qa_cache_service.put(
        cache,
        key=key,
        answer=answer.answer,
        kind=answer.kind,
        refused=answer.refused,
        refusal_reason=answer.refusal_reason,
        suggestions=answer.suggestions,
        citations=answer.citations,
        prompt_version=answer.prompt_version,
        model=answer.model,
        ttl_seconds=60,
    )


def test_prepare_ask_cache_hit_skips_rewrite_and_retrieval(monkeypatch) -> None:
    from tests.test_qa_service import FakeSession

    cache = MemoryCache()
    question = " 错位相减 法 "
    key = qa_cache_service.cache_key(18, question, _scope())
    _put(cache, key, _cache_answer())
    monkeypatch.setattr(qa_service, "get_cache", lambda: cache)
    monkeypatch.setattr(
        qa_service,
        "rewrite_query",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应改写")),
    )

    session = FakeSession()
    plan = qa_service.prepare_ask(
        session,
        user_id=18,
        question=question,
        scope=_scope(),
        conversation_id=None,
    )

    assert plan.cached is not None
    assert plan.kind == "rag"
    assert plan.prepared is None
    assert [(c.note_id, c.chunk_id) for c in plan.citations] == [(55, 101)]
    assert session.commits == 1
    assert session.added[1].role == "user"
    assert session.added[1].content_md == "错位相减 法"


def test_stream_events_cache_hit_persists_zero_token_assistant() -> None:
    from tests.test_qa_service import FakeAssistantSession

    session = FakeAssistantSession()
    plan = qa_service.QaPlan(
        user_id=18,
        conversation_id=12,
        user_message_id=20,
        question="问题",
        kind="rag",
        prepared=None,
        chitchat_reply=None,
        citations=[
            qa_service.QaCitationMeta(
                index=1,
                note_id=55,
                chunk_id=101,
                title="数列笔记",
                heading_path="数列/错位相减法",
                page_no=2,
                snippet="错位相减法正文",
            )
        ],
        prompt_version="qa/v2",
        rewrite=None,
        started_at=0.0,
        cached=_cache_answer(),
        cache_key="qa:v1:18:scope:q",
    )

    events = list(
        qa_service.stream_events(plan, session_factory=lambda: session)
    )
    assert [event.event for event in events] == ["meta", "delta", "done"]
    done = events[-1].data
    assert done["cached"] is True
    assert done["tokens"] == 0
    assert done["refused"] is False
    message = session.added[0]
    assert message.content_md == "缓存回答[1]"
    assert message.token_usage["total_tokens"] == 0
    assert message.model == "qwen-plus"
    assert session.added[1].chunk_id == 101


def test_stream_events_successful_rag_writes_cache(monkeypatch) -> None:
    from tests.test_qa_service import FakeAssistantSession, _plan

    cache = MemoryCache()
    monkeypatch.setattr(qa_service, "get_cache", lambda: cache)

    def fake_stream(prepared, *, llm_client=None, messages=None):
        yield AnswerChunk(text="答[1]")
        yield AnswerChunk(response=_response("答[1]"))

    monkeypatch.setattr(qa_service, "stream_answer", fake_stream)
    base_plan = _plan()
    plan = replace(
        base_plan,
        cache_key=qa_cache_service.cache_key(18, base_plan.question, None),
    )
    events = list(
        qa_service.stream_events(
            plan, session_factory=lambda: FakeAssistantSession()
        )
    )
    assert events[-1].data["cached"] is False
    cached = qa_cache_service.get(
        cache, user_id=18, question=base_plan.question, scope=None
    )
    assert cached is not None
    assert cached.answer == "答[1]"
    assert cached.citations[0].chunk_id == 101


def _response(text: str):
    from app.ai.llm import LLMResponse

    return LLMResponse(
        text=text,
        model="qwen-plus",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        latency_ms=1,
        cost_yuan=0.00001,
    )


def _scope():
    from datetime import date

    from app.schemas.qa import QaScopeIn

    return QaScopeIn(subject_id=7, folder="函数", start_date=date(2026, 1, 1))