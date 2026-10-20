"""S1-6 Answerer：阈值/引用/重试/统计；全部 fake，禁止真实网络。"""
from __future__ import annotations

import pytest

from app.ai.llm.base import LLMClient, LLMMessage, LLMResponse
from app.ai.llm.errors import LLMError
from app.ai.rag import answerer
from app.ai.rag.answerer import (
    REFUSAL_TEXT,
    answer_question,
    extract_citation_indices,
    validate_citations,
)
from app.ai.rag.retriever import RerankInfo, RetrievalResult, RetrievedChunk


def _chunk(chunk_id: int = 1, score: float | None = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        note_id=107,
        source_file_id=107,
        chunk_index=0,
        content="错位相减法：乘公比、错位减、等比求和、再化简。",
        heading_path="数列/错位相减法",
        page_no=2,
        rerank_score=score,
    )


def _retrieval(chunks: list[RetrievedChunk], *, fallback: bool = False) -> RetrievalResult:
    info = RerankInfo(
        model="qwen3-rerank",
        candidates=30,
        top_k=6,
        tokens=10,
        latency_ms=5,
        cost_yuan=0.0,
        fallback=fallback,
    )
    return RetrievalResult(
        query="错位相减法怎么用？",
        tsquery="错位 & 相减",
        vector=chunks,
        fulltext=chunks,
        fused=chunks,
        reranked=chunks,
        elapsed_ms=7,
        rerank_info=info,
    )


class FakeLLM(LLMClient):
    def __init__(self, texts: list[str] | None = None, error: Exception | None = None) -> None:
        super().__init__(model="fake")
        self.texts = list(texts or [])
        self.error = error
        self.calls: list[list[LLMMessage]] = []

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        text = self.texts.pop(0) if self.texts else ""
        return LLMResponse(
            text=text,
            model="fake",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            latency_ms=1,
            cost_yuan=0.00001,
        )


def _patch(monkeypatch, result: RetrievalResult) -> None:
    monkeypatch.setattr(
        answerer,
        "retrieve_hybrid_reranked",
        lambda *args, **kwargs: result,
    )


def test_extract_citation_indices_dedupes_and_sorts() -> None:
    assert extract_citation_indices("[2][1][2]") == [1, 2]


def test_validate_citations_accepts_valid() -> None:
    ok, indices = validate_citations("[1][2]", context_size=2)
    assert ok is True
    assert indices == [1, 2]


def test_validate_citations_rejects_out_of_range() -> None:
    ok, indices = validate_citations("[3]", context_size=2)
    assert ok is False
    assert indices == [3]


def test_validate_citations_rejects_missing() -> None:
    ok, indices = validate_citations("没有引用", context_size=2)
    assert ok is False
    assert indices == []


def test_answer_question_refuses_no_context_without_llm(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([]))
    fake = FakeLLM(["不应调用"])
    result = answer_question(object(), "问题", user_id=1, llm_client=fake)
    assert result.refused is True
    assert result.refusal_reason == "no_context"
    assert result.llm_calls == 0
    assert fake.calls == []


def test_answer_question_refuses_low_score_without_llm(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk(score=0.1)]))
    fake = FakeLLM(["不应调用"])
    result = answer_question(
        object(), "问题", user_id=1, threshold=0.45, llm_client=fake
    )
    assert result.refused is True
    assert result.refusal_reason == "low_score"
    assert result.llm_calls == 0
    assert fake.calls == []


def test_answer_question_answers_with_citations(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk()]))
    fake = FakeLLM(["错位相减法：乘公比、错位减、等比求和、再化简。[1]"])
    result = answer_question(object(), "问题", user_id=1, llm_client=fake)
    assert result.refused is False
    assert result.answer.endswith("[1]")
    assert len(result.citations) == 1
    assert result.citations[0].note_id == 107
    assert result.citations[0].index == 1
    assert result.llm_calls == 1
    assert result.citation_retry_count == 0


def test_answer_question_retries_invalid_citation_once(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk()]))
    fake = FakeLLM(["错误引用[99]", "正确引用[1]"])
    result = answer_question(object(), "问题", user_id=1, llm_client=fake)
    assert result.refused is False
    assert result.citation_retry_count == 1
    assert result.llm_calls == 2
    assert len(fake.calls) == 2
    assert "[1]..[1]" in fake.calls[1][-1].content


def test_answer_question_refuses_after_citation_retry(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk()]))
    fake = FakeLLM(["[99]", "[98]"])
    result = answer_question(object(), "问题", user_id=1, llm_client=fake)
    assert result.refused is True
    assert result.refusal_reason == "citation_invalid"
    assert result.answer == REFUSAL_TEXT
    assert result.citations == []
    assert result.citation_retry_count == 1


def test_answer_question_empty_answer_retries_then_refuses(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk()]))
    fake = FakeLLM(["", ""])
    result = answer_question(object(), "问题", user_id=1, llm_client=fake)
    assert result.refused is True
    assert result.refusal_reason == "empty_answer"
    assert result.llm_calls == 2


def test_answer_question_rerank_fallback_skips_threshold(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk(score=None)], fallback=True))
    fake = FakeLLM(["回答[1]"])
    result = answer_question(
        object(), "问题", user_id=1, threshold=0.99, llm_client=fake
    )
    assert result.refused is False
    assert result.degraded is True
    assert result.top_rerank_score is None
    assert result.llm_calls == 1


def test_answer_question_no_scores_degrades(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk(score=None)], fallback=False))
    fake = FakeLLM(["回答[1]"])
    result = answer_question(
        object(), "问题", user_id=1, threshold=0.99, llm_client=fake
    )
    assert result.refused is False
    assert result.degraded is True
    assert result.llm_calls == 1


def test_answer_question_does_not_swallow_llm_error(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk()]))
    fake = FakeLLM(error=LLMError("boom"))
    with pytest.raises(LLMError):
        answer_question(object(), "问题", user_id=1, llm_client=fake)


def test_answer_question_rejects_invalid_threshold(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk()]))
    with pytest.raises(ValueError):
        answer_question(object(), "问题", user_id=1, threshold=1.1)