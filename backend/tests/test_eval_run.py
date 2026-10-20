"""S1-7 运行器：只测路由/渲染/CLI 冒烟，不连 DB、不调外部。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval.qa_eval import load_config  # noqa: E402
from eval import run  # noqa: E402


class FakeEmbedding:
    pass


class FakeRerank:
    model = "fake-rerank"


def _result(*, vector=None, fused=None, reranked=None, elapsed=10, rerank_ms=5):
    return SimpleNamespace(
        vector=vector or [],
        fused=fused or [],
        reranked=reranked or [],
        elapsed_ms=elapsed,
        rerank_info=SimpleNamespace(latency_ms=rerank_ms),
    )


def test_resolve_dataset_and_config() -> None:
    assert run._resolve_dataset("qa_set").name == "qa_set.jsonl"
    assert run._resolve_config("hybrid_rerank").name == "hybrid_rerank.json"


def test_retrieve_vector_uses_vector_list(monkeypatch) -> None:
    cfg = load_config(ROOT / "eval" / "configs" / "vector.json")
    calls = []

    def fake_retrieve(session, question, **kwargs):
        calls.append(kwargs)
        return _result(
            vector=[SimpleNamespace(chunk_id=1)],
            fused=[SimpleNamespace(chunk_id=2)],
        )

    monkeypatch.setattr(run, "retrieve_hybrid", fake_retrieve)
    hits, latency = run._retrieve(
        object(),
        "q",
        cfg,
        user_id=1,
        embedding_client=FakeEmbedding(),
        rerank_client=FakeRerank(),
    )
    assert [hit.chunk_id for hit in hits] == [1]
    assert latency == 10
    assert calls[0]["top_k"] == 20


def test_retrieve_hybrid_uses_fused_list(monkeypatch) -> None:
    cfg = load_config(ROOT / "eval" / "configs" / "hybrid.json")
    monkeypatch.setattr(
        run,
        "retrieve_hybrid",
        lambda *a, **k: _result(
            vector=[SimpleNamespace(chunk_id=1)],
            fused=[SimpleNamespace(chunk_id=2)],
        ),
    )
    hits, _ = run._retrieve(
        object(),
        "q",
        cfg,
        user_id=1,
        embedding_client=FakeEmbedding(),
        rerank_client=FakeRerank(),
    )
    assert [hit.chunk_id for hit in hits] == [2]


def test_retrieve_rerank_adds_rerank_latency(monkeypatch) -> None:
    cfg = load_config(ROOT / "eval" / "configs" / "hybrid_rerank.json")
    monkeypatch.setattr(
        run,
        "retrieve_hybrid_reranked",
        lambda *a, **k: _result(
            reranked=[SimpleNamespace(chunk_id=3)], elapsed=20, rerank_ms=7
        ),
    )
    hits, latency = run._retrieve(
        object(),
        "q",
        cfg,
        user_id=1,
        embedding_client=FakeEmbedding(),
        rerank_client=FakeRerank(),
    )
    assert [hit.chunk_id for hit in hits] == [3]
    assert latency == 27


def test_render_markdown_uses_dash_for_null_answer() -> None:
    payload = {
        "dataset": "qa_set",
        "config": "vector",
        "case_count": 30,
        "retrieval": {"hit_at_5": 0.5, "mrr_at_5": 0.4, "avg_latency_ms": 120.0},
        "answer": None,
        "answer_skipped": True,
        "cases": [],
    }
    text = run._render_summary_markdown(payload)
    assert "| 配置 |" in text
    assert "vector" in text
    assert "—" in text


def test_render_markdown_includes_answer_metrics() -> None:
    payload = {
        "dataset": "qa_set",
        "config": "hybrid_rerank",
        "case_count": 30,
        "retrieval": {"hit_at_5": 0.8, "mrr_at_5": 0.6, "avg_latency_ms": 100.0},
        "answer": {
            "citation_precision": 0.9,
            "citation_hit_rate": 0.85,
            "refusal_accuracy": 1.0,
            "confusion": {"tp": 10, "fp": 0, "fn": 0, "tn": 20},
            "avg_total_tokens": 1200.0,
            "avg_latency_ms": 3000.0,
            "total_cost_yuan": 0.01,
            "llm_calls": 20,
            "citation_retry_count": 0,
            "answered_count": 20,
        },
        "answer_skipped": False,
        "cases": [],
    }
    text = run._render_summary_markdown(payload)
    assert "0.900" in text
    assert "0.850" in text
    assert "100.0%" in text
    assert "¥0.010000" in text


def test_eval_run_help_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "eval" / "run.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage" in result.stdout.lower()