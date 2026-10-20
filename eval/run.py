"""S1-7 评测 CLI：三配置检索 + 生产链路回答指标。

用法（仓库根目录）：
    python eval/run.py --dataset qa_set --config hybrid_rerank
    python eval/run.py --dataset qa_set --config vector --skip-answer
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.ai.embedding import get_embedding_client  # noqa: E402
from app.ai.embedding.errors import EmbeddingError  # noqa: E402
from app.ai.llm import get_llm_client  # noqa: E402
from app.ai.llm.errors import LLMError  # noqa: E402
from app.ai.rag.answerer import answer_question  # noqa: E402
from app.ai.rag.retriever import (  # noqa: E402
    RetrievalResult,
    RetrievedChunk,
    retrieve_hybrid,
    retrieve_hybrid_reranked,
)
from app.ai.rerank import RerankError, get_rerank_client  # noqa: E402
from app.core.context import set_trace_id  # noqa: E402
from app.core.db import new_session  # noqa: E402
from app.models.note_chunk import NoteChunk  # noqa: E402
from eval.qa_eval import (  # noqa: E402
    AnswerSummary,
    CaseAnswer,
    CaseRetrieval,
    DatasetError,
    EvalConfigError,
    QACase,
    RetrievalConfig,
    citation_hit,
    citation_precision,
    first_gold_rank,
    load_config,
    load_dataset,
    summarize_answer,
    summarize_retrieval,
    validate_gold_chunks,
)


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                pass


def _resolve_dataset(value: str) -> Path:
    path = Path(value)
    if path.suffix == ".jsonl" or path.is_file():
        return path
    return ROOT / "eval" / "datasets" / f"{value}.jsonl"


def _resolve_config(value: str) -> Path:
    path = Path(value)
    if path.suffix == ".json" or path.is_file():
        return path
    return ROOT / "eval" / "configs" / f"{value}.json"


def _retrieve(
    session,
    question: str,
    cfg: RetrievalConfig,
    *,
    user_id: int,
    embedding_client,
    rerank_client,
) -> tuple[list[RetrievedChunk], int]:
    if cfg.retrieval == "vector":
        result: RetrievalResult = retrieve_hybrid(
            session,
            question,
            user_id=user_id,
            top_k=cfg.top_k,
            client=embedding_client,
        )
        return result.vector[: cfg.top_n], result.elapsed_ms
    if cfg.retrieval == "hybrid":
        result = retrieve_hybrid(
            session,
            question,
            user_id=user_id,
            top_k=cfg.top_k,
            client=embedding_client,
        )
        return result.fused[: cfg.top_n], result.elapsed_ms
    result = retrieve_hybrid_reranked(
        session,
        question,
        user_id=user_id,
        top_k=cfg.top_k,
        rerank_candidates=cfg.rerank_candidates,
        rerank_top_k=cfg.rerank_top_k,
        client=embedding_client,
        rerank_client=rerank_client,
    )
    extra = result.rerank_info.latency_ms if result.rerank_info else 0
    return result.reranked[: cfg.top_n], result.elapsed_ms + extra


def _answer_case(
    session,
    case: QACase,
    cfg: RetrievalConfig,
    *,
    user_id: int,
    embedding_client,
    rerank_client,
    llm_client,
) -> tuple[CaseAnswer, int, int]:
    result = answer_question(
        session,
        case.question,
        user_id=user_id,
        top_k=cfg.top_k,
        embedding_client=embedding_client,
        rerank_client=rerank_client,
        llm_client=llm_client,
    )
    cited = [citation.chunk_id for citation in result.citations]
    gold = set(case.gold_chunk_ids)
    if case.should_refuse:
        precision = None
        matched = None
    elif result.refused:
        precision = 0.0
        matched = False
    else:
        precision = citation_precision(cited, gold)
        matched = citation_hit(cited, gold)
    answer = CaseAnswer(
        case_id=case.id,
        refused=result.refused,
        refusal_reason=result.refusal_reason,
        cited_chunk_ids=cited,
        citation_precision=precision,
        citation_hit=matched,
        total_tokens=result.total_tokens,
        latency_ms=result.latency_ms,
        cost_yuan=result.cost_yuan,
    )
    return answer, result.llm_calls, result.citation_retry_count


def _render_summary_markdown(payload: dict[str, Any]) -> str:
    retrieval = payload["retrieval"]
    answer = payload["answer"]
    lines = [
        "# S1-7 自测结果",
        "",
        f"- 数据集：`{payload['dataset']}`（{payload['case_count']} 条）",
        f"- 配置：`{payload['config']}`",
        f"- 生成时间：{payload.get('generated_at', '—')}",
        "",
        "| 配置 | hit@5 | MRR@5 | 引用精确率 | 引用命中率 | 拒答准确率 | 平均延迟 | 平均 tokens | 总费用 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    if answer is None:
        lines.append(
            f"| {payload['config']} | {retrieval['hit_at_5']:.3f} | "
            f"{retrieval['mrr_at_5']:.3f} | — | — | — | "
            f"{retrieval['avg_latency_ms']:.0f}ms | — | — |"
        )
    else:
        lines.append(
            f"| {payload['config']} | {retrieval['hit_at_5']:.3f} | "
            f"{retrieval['mrr_at_5']:.3f} | {answer['citation_precision']:.3f} | "
            f"{answer['citation_hit_rate']:.3f} | "
            f"{answer['refusal_accuracy'] * 100:.1f}% | "
            f"{answer['avg_latency_ms']:.0f}ms | "
            f"{answer['avg_total_tokens']:.1f} | "
            f"¥{answer['total_cost_yuan']:.6f} |"
        )
    lines += [
        "",
        f"- 检索平均延迟：{retrieval['avg_latency_ms']:.0f}ms",
    ]
    if answer is not None:
        lines += [
            f"- 拒答混淆矩阵：{answer['confusion']}",
            f"- answered_count：{answer['answered_count']}",
            f"- llm_calls：{answer['llm_calls']}",
            f"- citation_retry_count：{answer['citation_retry_count']}",
        ]
    else:
        lines.append("- 回答指标：未运行（--skip-answer 或非生产配置）")
    lines.append("")
    return "\n".join(lines)


def _write_outputs(payload: dict[str, Any], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    markdown = _render_summary_markdown(payload)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(markdown, encoding="utf-8")


def _build_payload(
    *,
    dataset_name: str,
    config_name: str,
    user_id: int,
    cases: list[QACase],
    retrieval_summary,
    answer_summary: AnswerSummary | None,
    answer_skipped: bool,
    case_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "dataset": dataset_name,
        "config": config_name,
        "user_id": user_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "case_count": len(cases),
        "answerable_count": sum(1 for case in cases if not case.should_refuse),
        "refusal_count": sum(1 for case in cases if case.should_refuse),
        "answer_skipped": answer_skipped,
        "retrieval": {
            "hit_at_5": retrieval_summary.hit_at_5,
            "mrr_at_5": retrieval_summary.mrr_at_5,
            "avg_latency_ms": retrieval_summary.avg_latency_ms,
        },
        "answer": None
        if answer_summary is None
        else {
            "citation_precision": answer_summary.citation_precision,
            "citation_hit_rate": answer_summary.citation_hit_rate,
            "refusal_accuracy": answer_summary.refusal_accuracy,
            "confusion": answer_summary.confusion,
            "avg_total_tokens": answer_summary.avg_total_tokens,
            "avg_latency_ms": answer_summary.avg_latency_ms,
            "total_cost_yuan": answer_summary.total_cost_yuan,
            "llm_calls": answer_summary.llm_calls,
            "citation_retry_count": answer_summary.citation_retry_count,
            "answered_count": answer_summary.answered_count,
        },
        "cases": case_rows,
    }


def main() -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="S1-7 自测问答评测")
    parser.add_argument("--dataset", required=True, help="qa_set 或 .jsonl 路径")
    parser.add_argument(
        "--config",
        required=True,
        help="vector/hybrid/hybrid_rerank 或 .json 路径",
    )
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--skip-answer", action="store_true", help="只跑检索，不调 LLM")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--md-output", type=Path, default=None)
    args = parser.parse_args()

    dataset_path = _resolve_dataset(args.dataset)
    config_path = _resolve_config(args.config)
    try:
        cases = load_dataset(dataset_path)
        cfg = load_config(config_path)
    except (DatasetError, EvalConfigError) as exc:
        print(f"数据/配置错误：{exc}", file=sys.stderr)
        return 2

    answer_enabled = cfg.retrieval == "hybrid_rerank" and not args.skip_answer
    set_trace_id("s1-7-eval-" + uuid.uuid4().hex[:12])

    try:
        embedding_client = get_embedding_client()
        rerank_client = get_rerank_client() if cfg.retrieval == "hybrid_rerank" else None
        llm_client = get_llm_client() if answer_enabled else None
        retrieval_rows: list[CaseRetrieval] = []
        answer_rows: list[CaseAnswer] = []
        case_rows: list[dict[str, Any]] = []
        llm_calls = 0
        citation_retry_count = 0
        with new_session() as session:
            owner_rows = session.execute(
                select(NoteChunk.id, NoteChunk.note_id).where(
                    NoteChunk.user_id == args.user_id
                )
            ).all()
            validate_gold_chunks(cases, {row.id: row.note_id for row in owner_rows})

            for case in cases:
                hits, latency_ms = _retrieve(
                    session,
                    case.question,
                    cfg,
                    user_id=args.user_id,
                    embedding_client=embedding_client,
                    rerank_client=rerank_client,
                )
                rank = (
                    first_gold_rank(hits, set(case.gold_chunk_ids))
                    if not case.should_refuse
                    else None
                )
                retrieval_rows.append(
                    CaseRetrieval(
                        case_id=case.id,
                        hit_at_5=rank is not None,
                        first_gold_rank=rank,
                        latency_ms=latency_ms,
                    )
                )
                answer_row = None
                if answer_enabled:
                    answer_row, calls, retries = _answer_case(
                        session,
                        case,
                        cfg,
                        user_id=args.user_id,
                        embedding_client=embedding_client,
                        rerank_client=rerank_client,
                        llm_client=llm_client,
                    )
                    answer_rows.append(answer_row)
                    llm_calls += calls
                    citation_retry_count += retries
                case_rows.append(
                    {
                        "id": case.id,
                        "question": case.question,
                        "scope": case.scope,
                        "should_refuse": case.should_refuse,
                        "gold_chunk_ids": case.gold_chunk_ids,
                        "hit_at_5": rank is not None if not case.should_refuse else None,
                        "first_gold_rank": rank,
                        "retrieval_latency_ms": latency_ms,
                        "answer": None
                        if answer_row is None
                        else {
                            "refused": answer_row.refused,
                            "refusal_reason": answer_row.refusal_reason,
                            "cited_chunk_ids": answer_row.cited_chunk_ids,
                            "citation_precision": answer_row.citation_precision,
                            "citation_hit": answer_row.citation_hit,
                            "total_tokens": answer_row.total_tokens,
                            "latency_ms": answer_row.latency_ms,
                            "cost_yuan": answer_row.cost_yuan,
                        },
                    }
                )

        retrieval_summary = summarize_retrieval(cases, retrieval_rows)
        answer_summary = (
            None
            if not answer_enabled
            else summarize_answer(
                cases,
                answer_rows,
                llm_calls=llm_calls,
                citation_retry_count=citation_retry_count,
            )
        )
        config_name = cfg.name
        json_path = args.output or (
            ROOT / "eval" / "results" / f"s1-7-{config_name}.json"
        )
        md_path = args.md_output or (
            ROOT / "eval" / "results" / f"s1-7-{config_name}.md"
        )
        payload = _build_payload(
            dataset_name=dataset_path.stem,
            config_name=config_name,
            user_id=args.user_id,
            cases=cases,
            retrieval_summary=retrieval_summary,
            answer_summary=answer_summary,
            answer_skipped=not answer_enabled,
            case_rows=case_rows,
        )
        _write_outputs(payload, json_path, md_path)
        print(_render_summary_markdown(payload))
        print(f"JSON：{json_path}")
        print(f"Markdown：{md_path}")
        return 0
    except DatasetError as exc:
        print(f"数据/配置错误：{exc}", file=sys.stderr)
        return 2
    except OperationalError:
        print(
            "数据库连接失败：请先启动基础服务 "
            "docker compose -f deploy/docker-compose.dev.yml up -d",
            file=sys.stderr,
        )
        return 3
    except (EmbeddingError, RerankError, LLMError) as exc:
        print(f"外部调用失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())