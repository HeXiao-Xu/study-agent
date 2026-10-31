"""S3-5 qa_service：FakeSession，不连库、不调外部 LLM。"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.ai.llm import LLMError, LLMResponse
from app.ai.rag.answerer import REFUSAL_TEXT, AnswerChunk, PreparedAnswer
from app.ai.rag.prompt_builder import BuiltContext, Citation, ContextItem
from app.ai.rag.query_rewriter import HistoryTurn
from app.ai.rag.retriever import RetrievalResult
from app.core.exceptions import NotFoundError
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.message_citation import MessageCitation
from app.schemas.qa import QaAskRequest, QaScopeIn
from app.services import qa_service
from app.services.query_rewrite import RewriteResult


class FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = list(rows)

    def all(self) -> list[object]:
        return list(self._rows)


class FakeSession:
    def __init__(
        self,
        *,
        scalar_results: list[object | None] | None = None,
        scalars_results: list[list[object]] | None = None,
        execute_rows: list[list[tuple[object, object]]] | None = None,
    ) -> None:
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.execute_rows = list(execute_rows or [])
        self.added: list[object] = []
        self.commits = 0
        self.flushes = 0

    def scalar(self, statement: object) -> object | None:
        return self.scalar_results.pop(0)

    def scalars(self, statement: object) -> FakeResult:
        return FakeResult(self.scalars_results.pop(0))

    def execute(self, statement: object) -> FakeResult:
        return FakeResult(self.execute_rows.pop(0))

    def add(self, instance: object) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = 100 + len(self.added)  # type: ignore[attr-defined]
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]
        self.added.append(instance)

    def flush(self) -> None:
        self.flushes += 1

    def commit(self) -> None:
        self.commits += 1


def _scope() -> QaScopeIn:
    return QaScopeIn(subject_id=7, folder="函数", start_date=date(2026, 1, 1))


def _rewrite(*, intent: str = "note_query", reply: str | None = None) -> RewriteResult:
    return RewriteResult(
        intent=intent,  # type: ignore[arg-type]
        rewritten_query="改写后的问题",
        reply=reply,
        is_followup=True,
        degraded=False,
        cache_hit=False,
        llm_calls=1,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cost_yuan=0.00001,
        latency_ms=2,
        error=None,
    )


def _citation(index: int = 1) -> Citation:
    return Citation(
        index=index,
        note_id=55,
        chunk_id=101,
        source_file_id=9,
        heading_path="数列/错位相减法",
        page_no=2,
        snippet="错位相减法正文",
        rerank_score=0.9,
    )


def _prepared() -> PreparedAnswer:
    item = ContextItem(citation=_citation(), content="错位相减法正文", tokens=10)
    built = BuiltContext(text="[1] 正文", items=[item], tokens=10, truncated=False)
    return PreparedAnswer(
        retrieval=RetrievalResult(
            query="改写后的问题",
            tsquery="错位",
            vector=[],
            fulltext=[],
            fused=[],
            reranked=[],
            elapsed_ms=5,
        ),
        built=built,
        prompt="rendered prompt",
        refused=None,
        retrieval_ms=5,
        top_score=0.9,
        degraded=False,
    )


def test_qa_ask_request_rejects_bad_conversation_id_and_blank_question() -> None:
    with pytest.raises(ValidationError):
        QaAskRequest(question="  ")
    with pytest.raises(ValidationError):
        QaAskRequest(question="问题", conversation_id="abc")
    with pytest.raises(ValidationError):
        QaAskRequest(question="问题", conversation_id="0")


def test_qa_scope_rejects_reversed_dates_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        QaScopeIn(start_date=date(2026, 2, 1), end_date=date(2026, 1, 1))
    with pytest.raises(ValidationError):
        QaScopeIn(chunk_types=["note"])  # QA scope 不允许 chunk_types


def test_prepare_ask_creates_conversation_user_message_and_plan(monkeypatch) -> None:
    session = FakeSession(execute_rows=[[(55, "数列笔记")]])
    fake_rewrite = _rewrite()
    calls: dict[str, object] = {}

    def fake_rewrite_query(question, *, history, use_cache=True):
        calls["rewrite"] = (question, history)
        return fake_rewrite

    monkeypatch.setattr(qa_service, "rewrite_query", fake_rewrite_query)
    monkeypatch.setattr(
        qa_service.prompt_service,
        "get_active_prompt",
        lambda session, name="qa": type(
            "P", (), {"name": "qa", "version": "v2", "content": "PROMPT"}
        )(),
    )

    def fake_prepare(session, question, **kwargs):
        calls["prepare"] = (question, kwargs)
        return _prepared()

    monkeypatch.setattr(qa_service, "prepare_answer", fake_prepare)

    plan = qa_service.prepare_ask(
        session,
        user_id=18,
        question="错位相减法怎么用",
        scope=_scope(),
        conversation_id=None,
    )

    assert plan.kind == "rag"
    assert plan.prompt_version == "qa/v2"
    assert plan.citations[0].title == "数列笔记"
    assert plan.citations[0].index == 1
    conversation = next(item for item in session.added if isinstance(item, Conversation))
    assert conversation.title == "错位相减法怎么用"
    assert conversation.scope_json == {
        "subject_id": 7,
        "folder": "函数",
        "start_date": "2026-01-01",
        "end_date": None,
    }
    user_message = next(item for item in session.added if isinstance(item, Message))
    assert user_message.role == "user"
    assert user_message.content_md == "错位相减法怎么用"
    assert session.commits == 1
    assert calls["rewrite"] == ("错位相减法怎么用", [])
    prepare_call = calls["prepare"]
    assert isinstance(prepare_call, tuple)
    assert prepare_call[1]["retrieval_query"] == "改写后的问题"
    assert prepare_call[1]["scope"].subject_id == 7


def test_prepare_ask_inherits_stored_scope_and_passes_history(monkeypatch) -> None:
    conversation = Conversation(
        user_id=18,
        title="旧会话",
        scope_json={"subject_id": 3, "folder": None},
    )
    conversation.id = 12
    old_user = Message(conversation_id=12, role="user", content_md="上一问")
    old_user.id = 20
    old_assistant = Message(conversation_id=12, role="assistant", content_md="上一答")
    old_assistant.id = 21
    session = FakeSession(
        scalar_results=[conversation],
        scalars_results=[[old_assistant, old_user]],
        execute_rows=[[(55, "数列笔记")]],
    )
    calls: dict[str, object] = {}

    def fake_rewrite(question, *, history, use_cache=True):
        calls["history"] = history
        return _rewrite()

    monkeypatch.setattr(qa_service, "rewrite_query", fake_rewrite)
    monkeypatch.setattr(
        qa_service.prompt_service,
        "get_active_prompt",
        lambda session, name="qa": type(
            "P", (), {"name": "qa", "version": "v1", "content": "PROMPT"}
        )(),
    )

    def fake_prepare(session, question, **kwargs):
        calls["scope"] = kwargs["scope"]
        return _prepared()

    monkeypatch.setattr(qa_service, "prepare_answer", fake_prepare)

    plan = qa_service.prepare_ask(
        session,
        user_id=18,
        question="追问",
        scope=None,
        conversation_id=12,
    )

    assert plan.conversation_id == 12
    assert calls["history"] == [
        HistoryTurn(role="user", content="上一问"),
        HistoryTurn(role="assistant", content="上一答"),
    ]
    assert calls["scope"].subject_id == 3


def test_prepare_ask_request_scope_overrides_stored(monkeypatch) -> None:
    conversation = Conversation(
        user_id=18, title="旧会话", scope_json={"subject_id": 3}
    )
    conversation.id = 12
    session = FakeSession(
        scalar_results=[conversation],
        scalars_results=[[]],
        execute_rows=[[]],
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(qa_service, "rewrite_query", lambda *a, **k: _rewrite())
    monkeypatch.setattr(
        qa_service.prompt_service,
        "get_active_prompt",
        lambda session, name="qa": type(
            "P", (), {"name": "qa", "version": "v1", "content": "PROMPT"}
        )(),
    )

    def fake_prepare(session, question, **kwargs):
        captured["scope"] = kwargs["scope"]
        return _prepared()

    monkeypatch.setattr(qa_service, "prepare_answer", fake_prepare)

    qa_service.prepare_ask(
        session,
        user_id=18,
        question="追问",
        scope=_scope(),
        conversation_id=12,
    )

    assert captured["scope"].subject_id == 7


def test_prepare_ask_missing_conversation_raises_404() -> None:
    session = FakeSession(scalar_results=[None])
    with pytest.raises(NotFoundError):
        qa_service.prepare_ask(
            session,
            user_id=18,
            question="问题",
            scope=None,
            conversation_id=999,
        )


def test_prepare_ask_chitchat_skips_prompt_and_retrieval(monkeypatch) -> None:
    session = FakeSession()
    monkeypatch.setattr(
        qa_service,
        "rewrite_query",
        lambda *a, **k: _rewrite(intent="chitchat", reply="你好"),
    )
    monkeypatch.setattr(
        qa_service.prompt_service,
        "get_active_prompt",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("chitchat 不应查 Prompt")),
    )
    monkeypatch.setattr(
        qa_service,
        "prepare_answer",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("chitchat 不应检索")),
    )

    plan = qa_service.prepare_ask(
        session, user_id=18, question="你好", scope=None, conversation_id=None
    )

    assert plan.kind == "chitchat"
    assert plan.chitchat_reply == "你好"
    assert plan.prepared is None
    assert plan.citations == []


class FakeAssistantSession(FakeSession):
    def close(self) -> None:
        return None


def _plan(
    *,
    kind: str = "rag",
    prepared: PreparedAnswer | None = None,
    reply: str | None = None,
    prompt_version: str | None = "qa/v2",
) -> qa_service.QaPlan:
    return qa_service.QaPlan(
        user_id=18,
        conversation_id=12,
        user_message_id=30,
        question="问题",
        kind=kind,  # type: ignore[arg-type]
        prepared=(
            prepared
            if prepared is not None
            else (_prepared() if kind != "chitchat" else None)
        ),
        chitchat_reply=reply,
        citations=[
            qa_service.QaCitationMeta(
                index=1,
                note_id=55,
                chunk_id=101,
                title="数列笔记",
                heading_path="数列/错位相减法",
                page_no=2,
                snippet="正文",
            )
        ],
        prompt_version=prompt_version,
        rewrite=_rewrite(),
        started_at=0.0,
    )


def test_stream_events_rag_persists_assistant_and_citations(monkeypatch) -> None:
    final = LLMResponse(
        text="答[1]",
        model="qwen-plus",
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        latency_ms=5,
        cost_yuan=0.0001,
    )
    monkeypatch.setattr(
        qa_service,
        "stream_answer",
        lambda prepared, llm_client=None: iter(
            [
                AnswerChunk(text="答"),
                AnswerChunk(text="[1]"),
                AnswerChunk(response=final),
            ]
        ),
    )
    final_session = FakeAssistantSession()
    events = list(
        qa_service.stream_events(
            _plan(),
            llm_client=object(),
            session_factory=lambda: final_session,
        )
    )

    assert [event.event for event in events] == ["meta", "delta", "delta", "done"]
    assert events[0].data["conversation_id"] == "12"
    assert events[-1].data["refused"] is False
    assert events[-1].data["tokens"] == 135
    assistant = next(
        item for item in final_session.added if isinstance(item, Message)
    )
    assert assistant.role == "assistant"
    assert assistant.content_md == "答[1]"
    assert assistant.prompt_version == "qa/v2"
    assert assistant.token_usage["total_tokens"] == 120
    assert assistant.token_usage["rewrite"]["total_tokens"] == 15
    citations = [
        item for item in final_session.added if isinstance(item, MessageCitation)
    ]
    assert len(citations) == 1
    assert citations[0].rank == 1
    assert citations[0].chunk_id == 101
    assert final_session.commits == 1


def test_stream_events_chitchat_persists_reply(monkeypatch) -> None:
    final_session = FakeAssistantSession()
    events = list(
        qa_service.stream_events(
            _plan(
                kind="chitchat",
                prepared=None,
                reply="你好",
                prompt_version=None,
            ),
            session_factory=lambda: final_session,
        )
    )

    assert [event.event for event in events] == ["meta", "delta", "done"]
    assert events[1].data["text"] == "你好"
    assistant = next(
        item for item in final_session.added if isinstance(item, Message)
    )
    assert assistant.content_md == "你好"
    assert assistant.prompt_version is None


def test_stream_events_refused_persists_fixed_text(monkeypatch) -> None:
    prepared = replace(_prepared(), refused=object(), built=None)  # type: ignore[arg-type]
    final_session = FakeAssistantSession()
    events = list(
        qa_service.stream_events(
            _plan(kind="refused", prepared=prepared),
            session_factory=lambda: final_session,
        )
    )

    assert events[1].data["text"] == REFUSAL_TEXT
    assert events[-1].data["refused"] is True
    assistant = next(
        item for item in final_session.added if isinstance(item, Message)
    )
    assert assistant.content_md == REFUSAL_TEXT


def test_stream_events_llm_error_emits_error_and_no_assistant(monkeypatch) -> None:
    def boom(prepared, *, llm_client=None):
        raise LLMError("模拟失败")
        yield  # pragma: no cover

    monkeypatch.setattr(qa_service, "stream_answer", boom)
    final_session = FakeAssistantSession()
    events = list(
        qa_service.stream_events(_plan(), session_factory=lambda: final_session)
    )

    assert [event.event for event in events] == ["meta", "error"]
    assert events[-1].data["code"] == 50000
    assert not any(isinstance(item, Message) for item in final_session.added)


def test_stream_events_disconnect_does_not_persist_assistant(monkeypatch) -> None:
    closed: list[bool] = []

    class Stream:
        def __iter__(self):
            yield AnswerChunk(text="半截")
            raise GeneratorExit

        def close(self):
            closed.append(True)

    monkeypatch.setattr(
        qa_service, "stream_answer", lambda prepared, llm_client=None: Stream()
    )
    final_session = FakeAssistantSession()
    generator = qa_service.stream_events(
        _plan(), session_factory=lambda: final_session
    )
    assert next(generator).event == "meta"
    assert next(generator).event == "delta"
    with pytest.raises(StopIteration):
        next(generator)
    assert closed == [True]
    assert not any(isinstance(item, Message) for item in final_session.added)


def test_get_message_citations_returns_rows_and_404() -> None:
    message = Message(conversation_id=12, role="assistant", content_md="答")
    message.id = 31
    citation = MessageCitation(message_id=31, chunk_id=101, note_id=55, rank=1)
    citation.id = 99
    session = FakeSession(
        scalar_results=[message, None],
        scalars_results=[[citation], []],
    )

    rows = qa_service.get_message_citations(session, user_id=18, message_id=31)
    assert rows == [citation]

    with pytest.raises(NotFoundError):
        qa_service.get_message_citations(session, user_id=18, message_id=999)