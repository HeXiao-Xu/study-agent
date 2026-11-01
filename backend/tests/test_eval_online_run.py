"""S3-9 在线运行编排：fake client，不触网、不触库。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval import run  # noqa: E402
from eval.api_client import (  # noqa: E402
    AnswerResponse,
    ApiCitation,
    RetrievalResponse,
)
from eval.qa_eval import QACase, load_config  # noqa: E402


class FakeClient:
    def __init__(self) -> None:
        self.searches: list[tuple[str, str]] = []
        self.asks: list[str] = []
        self.deleted: list[str | None] = []

    def search(
        self, query: str, retrieval: str, *, top_k: int = 5
    ) -> RetrievalResponse:
        self.searches.append((query, retrieval))
        return RetrievalResponse(
            chunk_ids=[250, 251],
            latency_ms=5,
            rerank=retrieval == "hybrid_rerank",
        )

    def ask(self, question: str) -> AnswerResponse:
        self.asks.append(question)
        return AnswerResponse(
            text="答案",
            refused=False,
            refusal_reason=None,
            citations=[ApiCitation(250, "属性", "单调性", "定义", index=1)],
            cited_chunk_ids=[250],
            tokens=10,
            latency_ms=50,
            cost_yuan=0.001,
            conversation_id="99",
        )

    def delete_conversation(self, conversation_id: str | None) -> bool:
        self.deleted.append(conversation_id)
        return True


def _cases() -> list[QACase]:
    return [
        QACase(
            id="q001",
            question="单调性是什么？",
            scope="函数",
            gold_chunk_ids=[250],
            should_refuse=False,
        ),
        QACase(
            id="q002",
            question="今天天气？",
            scope="无关",
            gold_chunk_ids=[],
            should_refuse=True,
        ),
    ]


def test_run_api_config_vector_skips_answer() -> None:
    client = FakeClient()
    cfg = load_config(ROOT / "eval" / "configs" / "vector.json")

    retrieval, answers, rows = run._run_api_config(
        client, _cases(), cfg, answer_enabled=False
    )

    assert len(retrieval) == 2
    assert answers == []
    assert rows[0]["hit_at_5"] is True
    assert rows[0]["answer"] is None
    assert client.asks == []
    assert client.deleted == []


def test_run_api_config_production_answers_and_cleans_up() -> None:
    client = FakeClient()
    cfg = load_config(ROOT / "eval" / "configs" / "hybrid_rerank.json")

    retrieval, answers, rows = run._run_api_config(
        client, _cases(), cfg, answer_enabled=True
    )

    assert len(answers) == 2
    assert rows[0]["answer"]["text"] == "答案"
    assert rows[0]["answer"]["citations"][0]["chunk_id"] == 250
    assert client.asks == ["单调性是什么？", "今天天气？"]
    assert client.deleted == ["99", "99"]
    assert retrieval[0].latency_ms == 5


def test_render_compare_markdown_has_three_rows() -> None:
    payloads = [
        {
            "dataset": "qa_set_m2",
            "config": "vector",
            "case_count": 40,
            "retrieval": {
                "hit_at_5": 1.0,
                "mrr_at_5": 0.9,
                "avg_latency_ms": 100,
            },
            "answer": None,
        },
        {
            "dataset": "qa_set_m2",
            "config": "hybrid",
            "case_count": 40,
            "retrieval": {
                "hit_at_5": 1.0,
                "mrr_at_5": 0.8,
                "avg_latency_ms": 90,
            },
            "answer": None,
        },
        {
            "dataset": "qa_set_m2",
            "config": "hybrid_rerank",
            "case_count": 40,
            "retrieval": {
                "hit_at_5": 1.0,
                "mrr_at_5": 0.95,
                "avg_latency_ms": 300,
            },
            "answer": {
                "citation_precision": 0.8,
                "citation_hit_rate": 1.0,
                "refusal_accuracy": 1.0,
                "confusion": {"tp": 10, "fp": 0, "fn": 0, "tn": 30},
                "avg_total_tokens": 500,
                "avg_latency_ms": 3000,
                "total_cost_yuan": 0.02,
            },
        },
    ]
    text = run._render_compare_markdown(payloads)
    assert text.count("| vector |") == 1
    assert text.count("| hybrid |") == 1
    assert text.count("| hybrid_rerank |") == 1
    assert "0.950" in text
    assert "¥0.020000" in text