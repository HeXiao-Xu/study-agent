"""S1-7 指标纯函数。"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval.qa_eval import (  # noqa: E402
    AnswerSummary,
    CaseAnswer,
    CaseRetrieval,
    QACase,
    RetrievalSummary,
    citation_hit,
    citation_precision,
    first_gold_rank,
    hit_at_k,
    refusal_confusion,
    summarize_answer,
    summarize_retrieval,
)


@dataclass
class FakeHit:
    chunk_id: int


def _case(index: int, *, refuse: bool = False) -> QACase:
    return QACase(
        id=f"q{index:03d}",
        question=f"问题 {index}",
        scope="函数",
        gold_chunk_ids=[] if refuse else [index],
        should_refuse=refuse,
    )


def test_hit_at_5_true_false_and_empty() -> None:
    gold = {7}
    assert hit_at_k([FakeHit(1), FakeHit(7)], gold) is True
    assert hit_at_k([FakeHit(1), FakeHit(2)], gold) is False
    assert hit_at_k([], gold) is False


def test_first_gold_rank_returns_first_or_none() -> None:
    assert first_gold_rank([FakeHit(1), FakeHit(2), FakeHit(7)], {7}) == 3
    assert first_gold_rank([FakeHit(1)], {7}) is None
    assert first_gold_rank([FakeHit(1), FakeHit(2), FakeHit(3)], {1}, k=1) == 1


def test_first_gold_rank_rejects_bad_k() -> None:
    with pytest.raises(ValueError):
        first_gold_rank([], {1}, k=0)


def test_citation_precision_all_partial_zero() -> None:
    assert citation_precision([1, 2], {1, 2}) == 1.0
    assert citation_precision([1, 3], {1, 2}) == 0.5
    assert citation_precision([], {1}) == 0.0
    assert citation_precision([3], {1}) == 0.0


def test_citation_hit() -> None:
    assert citation_hit([1], {1, 2}) is True
    assert citation_hit([3], {1, 2}) is False
    assert citation_hit([], {1}) is False


def test_refusal_confusion_counts() -> None:
    cases = [_case(1), _case(2, refuse=True), _case(3, refuse=True), _case(4)]
    confused = refusal_confusion(
        cases,
        {"q001": False, "q002": True, "q003": False, "q004": True},
    )
    assert confused == {"tp": 1, "fp": 1, "fn": 1, "tn": 1}


def test_summarize_retrieval_excludes_refusal_denominator() -> None:
    cases = [_case(1), _case(2), _case(3, refuse=True)]
    records = [
        CaseRetrieval("q001", True, 1, 100),
        CaseRetrieval("q002", False, None, 300),
        CaseRetrieval("q003", False, None, 200),
    ]
    summary = summarize_retrieval(cases, records)
    assert isinstance(summary, RetrievalSummary)
    assert summary.hit_at_5 == 0.5
    assert summary.mrr_at_5 == 0.5
    assert summary.avg_latency_ms == 200.0


def test_summarize_answer_metrics_and_refusals() -> None:
    cases = [_case(1), _case(2), _case(3, refuse=True)]
    records = [
        CaseAnswer("q001", False, None, [1], 1.0, True, 100, 1000, 0.01),
        CaseAnswer("q002", True, "low_score", [], None, None, 0, 50, 0.0),
        CaseAnswer("q003", True, "low_score", [], None, None, 0, 50, 0.0),
    ]
    summary = summarize_answer(
        cases, records, llm_calls=1, citation_retry_count=0
    )
    assert isinstance(summary, AnswerSummary)
    assert summary.citation_precision == 0.5
    assert summary.citation_hit_rate == 0.5
    assert summary.refusal_accuracy == pytest.approx(2 / 3)
    assert summary.confusion == {"tp": 1, "fp": 1, "fn": 0, "tn": 1}
    assert summary.avg_total_tokens == pytest.approx(33.3333, rel=1e-3)
    assert summary.avg_latency_ms == pytest.approx(366.6667, rel=1e-3)
    assert summary.answered_count == 1