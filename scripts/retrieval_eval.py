"""S1-4 评测：10 个真实问题，纯向量 / 纯全文 / 混合三路 top5 对照（spec §10）。

用法（仓库根目录）：
    python scripts/retrieval_eval.py [--user-id 1] [--top-k 20] [--debug]

注意：问题与关键词在运行前固定；结果不理想时不要改它们粉饰。
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy.exc import OperationalError  # noqa: E402

from app.ai.embedding import get_embedding_client  # noqa: E402
from app.ai.embedding.errors import EmbeddingError  # noqa: E402
from app.ai.rag.retriever import RetrievalResult, retrieve_hybrid  # noqa: E402
from app.core.context import set_trace_id  # noqa: E402
from app.core.db import new_session  # noqa: E402

QUESTIONS: list[tuple[str, list[str]]] = [
    ("函数的定义域怎么求？", ["定义域"]),
    ("函数单调性的定义是什么？", ["单调性"]),
    ("如何用定义证明函数在区间上单调递增？", ["单调递增", "增函数"]),
    ("奇函数和偶函数有什么性质？", ["奇函数", "偶函数"]),
    ("二次函数在闭区间上的最值怎么求？", ["最大值", "最小值"]),
    ("分段函数 f(f(-1)) 怎么求？", ["f(f(-1))"]),
    ("函数 f(x)=x+1/x 在 (1,+∞) 上的单调性如何证明？", ["单调递增", "单调性"]),
    ("已知奇函数在 x≥0 时的解析式，怎么求 x<0 的解析式？", ["解析式"]),
    ("函数图象关于原点对称说明什么？", ["原点", "奇函数"]),
    ("商品定价最大利润问题怎么建模？", ["利润"]),
]


def _snippet(text: str, limit: int = 80) -> str:
    return " ".join(text.split())[:limit]


def _print_hits(title: str, hits: list, *, limit: int, kind: str) -> None:
    print(f"  {title}")
    if not hits:
        print("    （无命中）")
        return
    for rank, hit in enumerate(hits[:limit], start=1):
        if kind == "vector":
            score = f"d={hit.vector_distance:.4f}" if hit.vector_distance is not None else "d=-"
        elif kind == "fulltext":
            score = f"ts={hit.fulltext_score:.4f}" if hit.fulltext_score is not None else "ts=-"
        else:
            score = (
                f"rrf={hit.rrf_score:.5f} "
                f"v={hit.vector_rank or '-'} f={hit.fulltext_rank or '-'}"
            )
        heading = (hit.heading_path or "-")[:40]
        print(
            f"    {rank}. note={hit.note_id} chunk={hit.chunk_index} "
            f"heading={heading} {score}"
        )
        print(f"       {_snippet(hit.content)}")


def _first_hit_rank(hits: list, keywords: list[str], *, limit: int = 5) -> int:
    for rank, hit in enumerate(hits[:limit], start=1):
        content = hit.content.lower()
        if any(keyword.lower() in content for keyword in keywords):
            return rank
    return 0


def _print_summary(ranks: dict[str, list[int]]) -> None:
    total = len(QUESTIONS)
    print("=" * 78)
    print(f"汇总（{total} 问，hit@5 / MRR@5）")
    for name in ("vector", "fulltext", "hybrid"):
        values = ranks[name]
        hits = sum(1 for rank in values if rank)
        mrr = sum(1 / rank for rank in values if rank) / total
        print(f"  {name:9s} hit@5={hits}/{total}  MRR@5={mrr:.3f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="S1-4 混合检索三路对照评测")
    parser.add_argument("--user-id", type=int, default=1, help="用户 ID（默认 1）")
    parser.add_argument("--top-k", type=int, default=20, help="每路候选数（默认 20）")
    parser.add_argument("--debug", action="store_true", help="打印每路完整 top_k 与 RRF 明细")
    args = parser.parse_args()
    if args.top_k <= 0:
        parser.error("--top-k 必须为正整数")

    set_trace_id("retrieval-eval-" + uuid.uuid4().hex[:12])
    limit = args.top_k if args.debug else 5
    ranks: dict[str, list[int]] = {"vector": [], "fulltext": [], "hybrid": []}

    try:
        client = get_embedding_client()
        with new_session() as session:
            for index, (question, keywords) in enumerate(QUESTIONS, start=1):
                result: RetrievalResult = retrieve_hybrid(
                    session,
                    question,
                    user_id=args.user_id,
                    top_k=args.top_k,
                    client=client,
                )
                vector_rank = _first_hit_rank(result.vector, keywords)
                fulltext_rank = _first_hit_rank(result.fulltext, keywords)
                hybrid_rank = _first_hit_rank(result.fused, keywords)
                ranks["vector"].append(vector_rank)
                ranks["fulltext"].append(fulltext_rank)
                ranks["hybrid"].append(hybrid_rank)

                print(f"\n[{index}/{len(QUESTIONS)}] {question}")
                print(f"  tsquery: {result.tsquery or '（空）'}")
                _print_hits("纯向量 top5", result.vector, limit=limit, kind="vector")
                _print_hits("纯全文 top5", result.fulltext, limit=limit, kind="fulltext")
                _print_hits("混合 top5", result.fused, limit=limit, kind="hybrid")
                print(
                    f"  命中: vector={vector_rank or '-'} "
                    f"fulltext={fulltext_rank or '-'} hybrid={hybrid_rank or '-'}"
                )
    except OperationalError:
        print(
            "数据库连接失败：请先启动基础服务 "
            "docker compose -f deploy/docker-compose.dev.yml up -d",
            file=sys.stderr,
        )
        return 3
    except EmbeddingError as exc:
        print(f"Embedding 调用失败：{exc}", file=sys.stderr)
        return 2

    _print_summary(ranks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())