"""S3-5 qa_service：FakeSession，不连库、不调外部 LLM。"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.ai.rag.answerer import PreparedAnswer
from app.ai.rag.prompt_builder import BuiltContext, Citation, ContextItem
from app.ai.rag.query_rewriter import HistoryTurn
from app.ai.rag.retriever import RetrievalResult
from app.core.exceptions import NotFoundError
from app.models.conversation import Conversation
from app.models.message import Message
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