"""S3-3 真实改写验收：10 条指代追问 → 改写 → S3-2 检索 top3 → 期望关键词命中。

用法（仓库根目录，需真实 .env 与已入库笔记）：
    python scripts/rewrite_eval.py --user-id 1 --top-k 3

判定：top3 任一命中内容包含该条期望关键词记为命中；目标 hit@3 ≥ 8/10。
结果不理想时不要改问题或关键词粉饰。
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.context import set_trace_id  # noqa: E402
from app.core.db import new_session  # noqa: E402
from app.services.query_rewrite import HistoryTurn, rewrite_query  # noqa: E402
from app.services.retrieval_service import search_chunks  # noqa: E402

# (上一轮用户问题, 当前指代追问, 期望关键词)；期望关键词沿用 S1-5 固定问题集
CASES: list[tuple[str, str, list[str]]] = [
    ("函数的定义域怎么求？", "再详细解释一下，具体怎么做？", ["定义域"]),
    ("函数单调性的定义是什么？", "那它的前提条件呢？", ["单调性"]),
    ("如何用定义证明函数在区间上单调递增？", "再详细说一下这个证明。", ["单调递增", "增函数"]),
    ("奇函数和偶函数有什么性质？", "那它的图象有什么特点？", ["奇函数", "偶函数"]),
    ("二次函数在闭区间上的最值怎么求？", "再详细解释一下。", ["最大值", "最小值"]),
    ("分段函数 f(f(-1)) 怎么求？", "那它的步骤呢？", ["f(f(-1))"]),
    ("函数 f(x)=x+1/x 在 (1,+∞) 上的单调性如何证明？", "再详细说一下。", ["单调递增", "单调性"]),
    ("已知奇函数在 x≥0 时的解析式，怎么求 x<0 的解析式？", "那它的依据是什么？", ["解析式"]),
    ("函数图象关于原点对称说明什么？", "再详细解释一下。", ["原点", "奇函数"]),
    ("商品定价最大利润问题怎么建模？", "那它的步骤呢？", ["利润"]),
]


def _configure_stdio() -> None:
    """Windows 控制台默认 GBK；中文输出统一 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _snippet(text: str, limit: int = 70) -> str:
    return " ".join(text.split())[:limit]


def _contains(hits: list, keywords: list[str]) -> bool:
    return any(
        keyword.lower() in hit.content.lower()
        for hit in hits
        for keyword in keywords
    )


def main() -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="S3-3 指代追问改写 + 检索 hit@3 验收")
    parser.add_argument("--user-id", type=int, default=1, help="用户 ID（默认 1）")
    parser.add_argument("--top-k", type=int, default=3, help="检索返回条数（默认 3）")
    args = parser.parse_args()
    if args.top_k <= 0:
        parser.error("--top-k 必须为正整数")

    set_trace_id("rewrite-eval-" + uuid.uuid4().hex[:12])
    hits_total = 0
    degraded = 0
    total_tokens = 0
    total_cost = 0.0

    with new_session() as session:
        for index, (previous, followup, keywords) in enumerate(CASES, start=1):
            history = [
                HistoryTurn(role="user", content=previous),
                HistoryTurn(role="assistant", content="上一轮已解释相关概念。"),
            ]
            result = rewrite_query(followup, history=history, use_cache=False)
            total_tokens += result.total_tokens
            total_cost += result.cost_yuan
            degraded += 1 if result.degraded else 0

            print(
                f"\n[{index:02d}] {followup}\n"
                f"  上一轮: {previous}\n"
                f"  intent={result.intent} followup={result.is_followup} "
                f"degraded={result.degraded} cache={result.cache_hit}\n"
                f"  rewritten: {result.rewritten_query}"
            )

            if result.intent == "chitchat":
                print("  （闲聊，不检索）")
                continue

            response = search_chunks(
                session,
                user_id=args.user_id,
                query=result.rewritten_query or followup,
                top_k=args.top_k,
                rerank=False,
            )
            hit = _contains(response.hits, keywords)
            hits_total += 1 if hit else 0
            print(f"  hits={len(response.hits)} expected={keywords} hit={hit}")
            for rank, item in enumerate(response.hits, start=1):
                print(
                    f"    {rank}. note={item.note_id} chunk={item.chunk_index} "
                    f"type={item.chunk_type} {_snippet(item.content)}"
                )

        chitchat = rewrite_query("你好", use_cache=False)
        standalone = rewrite_query("函数的定义域怎么求？", use_cache=False)
        total_tokens += chitchat.total_tokens + standalone.total_tokens
        total_cost += chitchat.cost_yuan + standalone.cost_yuan
        print(
            f"\n[chitchat] intent={chitchat.intent} reply={chitchat.reply!r} "
            f"degraded={chitchat.degraded}"
        )
        print(
            f"[standalone] intent={standalone.intent} "
            f"followup={standalone.is_followup} rewritten={standalone.rewritten_query!r}"
        )

    print("\n" + "=" * 78)
    print(f"汇总：hit@3={hits_total}/{len(CASES)}  degraded={degraded}/{len(CASES)}")
    print(f"tokens={total_tokens}  cost=¥{total_cost:.6f}")
    checks_ok = (
        hits_total >= 8
        and chitchat.intent == "chitchat"
        and bool(chitchat.reply)
        and standalone.is_followup is False
    )
    print(f"目标 hit@3 ≥ 8/10 且闲聊/独立问题检查通过：{'PASS' if checks_ok else 'FAIL'}")
    return 0 if checks_ok else 2


if __name__ == "__main__":
    sys.exit(main())