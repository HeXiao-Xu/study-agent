"""S1-6 小校准：10 个应答题 + 5 个应拒题，只跑检索/rerank，不调 LLM。

用法：
    python scripts/calibrate_refusal.py
"""
from __future__ import annotations

import argparse
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy.exc import OperationalError  # noqa: E402

from app.ai.embedding.errors import EmbeddingError  # noqa: E402
from app.ai.rag.retriever import (  # noqa: E402
    RetrievalResult,
    retrieve_hybrid_reranked,
)
from app.core.context import set_trace_id  # noqa: E402
from app.core.db import new_session  # noqa: E402


def _configure_stdio() -> None:
    """Windows 控制台默认 GBK；标题/符号可能超出 GBK，统一 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, OSError):
                pass


ANSWERABLE_QUESTIONS = [
    "函数的定义域怎么求？",
    "函数单调性的定义是什么？",
    "如何用定义证明函数在区间上单调递增？",
    "奇函数和偶函数有什么性质？",
    "二次函数在闭区间上的最值怎么求？",
    "分段函数 f(f(-1)) 怎么求？",
    "函数 f(x)=x+1/x 在 (1,+∞) 上的单调性如何证明？",
    "已知奇函数在 x≥0 时的解析式，怎么求 x<0 的解析式？",
    "函数图象关于原点对称说明什么？",
    "商品定价最大利润问题怎么建模？",
]

REFUSAL_QUESTIONS = [
    "今天北京天气怎么样？",
    "怎么用 Python 写一个网页爬虫？",
    "《红楼梦》的作者是谁？",
    "出国留学需要准备哪些材料？",
    "今天股市行情怎么样？",
]


_SCHOOL_RE = re.compile(r"[\u4e00-\u9fa5]{2,}(?:大学|中学|学校)")


def _safe_heading(value: str | None) -> str:
    """校准输出不进真实校名；通用替换校名片段，不维护真实名单。"""
    if not value:
        return "未标注"
    return _SCHOOL_RE.sub("某学校", value)


def _top_score(result: RetrievalResult) -> float | None:
    scores = [
        chunk.rerank_score
        for chunk in result.reranked
        if chunk.rerank_score is not None
    ]
    return max(scores) if scores else None


def _print_result(
    label: str,
    question: str,
    result: RetrievalResult,
    score: float | None,
) -> None:
    top = result.reranked[0] if result.reranked else None
    fallback = bool(result.rerank_info and result.rerank_info.fallback)
    source = (
        f"note={top.note_id} page={top.page_no} heading={_safe_heading(top.heading_path)}"
        if top is not None
        else "无结果"
    )
    score_text = f"{score:.4f}" if score is not None else "N/A"
    print(f"[{label}] top1={score_text} fallback={fallback} {source}")
    print(f"  {question}")


def main() -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="S1-6 拒答阈值小校准（不调 LLM）")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=20)
    args = parser.parse_args()

    set_trace_id("calibrate-" + uuid.uuid4().hex[:12])
    answerable: list[float] = []
    refusal: list[float] = []
    try:
        with new_session() as session:
            for index, question in enumerate(ANSWERABLE_QUESTIONS, start=1):
                result = retrieve_hybrid_reranked(
                    session,
                    question,
                    user_id=args.user_id,
                    top_k=args.top_k,
                )
                score = _top_score(result)
                _print_result(f"应答题 {index}/10", question, result, score)
                if score is not None:
                    answerable.append(score)

            for index, question in enumerate(REFUSAL_QUESTIONS, start=1):
                result = retrieve_hybrid_reranked(
                    session,
                    question,
                    user_id=args.user_id,
                    top_k=args.top_k,
                )
                score = _top_score(result)
                _print_result(f"应拒题 {index}/5", question, result, score)
                if score is not None:
                    refusal.append(score)
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

    print("\n汇总：")
    if answerable:
        print(f"  应答题 top1 最低：{min(answerable):.4f}")
    else:
        print("  应答题 top1 最低：N/A")
    if refusal:
        print(f"  应拒题 top1 最高：{max(refusal):.4f}")
    else:
        print("  应拒题 top1 最高：N/A")
    if answerable and refusal and min(answerable) > max(refusal):
        print(
            f"  建议 τ 可取间隔中点：{(min(answerable) + max(refusal)) / 2:.4f}"
        )
    else:
        print("  当前小样本无法给出稳定间隔：需扩充语料/换分数口径，不能伪造通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())