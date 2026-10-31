"""S3-6 引用校验 5+5 真实验收。

用法：
    python scripts/citation_eval.py --user-id 18
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.db import new_session  # noqa: E402
from app.services import qa_service  # noqa: E402
from app.services.citation_checker import (  # noqa: E402
    SUPPLEMENT_PREFIX,
    check_answer,
)

NO_ANSWER_QUESTIONS = [
    "牛顿第二定律的适用条件是什么？",
    "如何用洛必达法则求极限？",
    "细胞有丝分裂各阶段的主要特征是什么？",
    "英语虚拟语气中过去完成时怎么用？",
    "化学平衡常数如何计算？",
]
PARTIAL_QUESTIONS = [
    "错位相减法的步骤是什么？它的历史起源是什么？",
    "错位相减法的适用条件是什么？三项乘积的数列怎么求和？",
    "函数奇偶性怎么判断？函数的最小正周期怎么求？",
    "函数单调性的定义是什么？含参函数单调性怎么讨论？",
    "错位相减法怎么用？它和倒序相加法有什么区别？",
]


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, OSError):
                pass


def run_case(question: str, *, user_id: int) -> dict[str, object]:
    session = new_session()
    try:
        plan = qa_service.prepare_ask(
            session,
            user_id=user_id,
            question=question,
            scope=None,
            conversation_id=None,
        )
    finally:
        session.close()

    events = list(qa_service.stream_events(plan))
    done = next(event for event in events if event.event == "done")
    text = "".join(
        str(event.data["text"])
        for event in events
        if event.event == "delta"
    )
    context_size = (
        len(plan.prepared.built.items)
        if plan.prepared is not None and plan.prepared.built is not None
        else 0
    )
    check = check_answer(text, context_size=context_size) if context_size else None
    return {
        "conversation_id": plan.conversation_id,
        "refused": done.data["refused"],
        "refusal_reason": done.data["refusal_reason"],
        "suggestions": len(done.data["suggestions"]),
        "has_prefix": SUPPLEMENT_PREFIX in text,
        "valid": check.valid_indices if check else [],
        "invalid": check.invalid_indices if check else [],
        "uncited": len(check.uncited_blocks) if check else 0,
        "message_id": done.data["message_id"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, required=True)
    args = parser.parse_args()
    _configure_stdio()

    rows: list[tuple[str, str, dict[str, object]]] = []
    for question in NO_ANSWER_QUESTIONS:
        rows.append(
            ("no_answer", question, run_case(question, user_id=args.user_id))
        )
    for question in PARTIAL_QUESTIONS:
        rows.append(
            ("partial", question, run_case(question, user_id=args.user_id))
        )

    failures = 0
    for kind, question, result in rows:
        expected_refused = kind == "no_answer"
        ok = bool(result["refused"]) == expected_refused
        if kind == "partial":
            ok = ok and not result["refused"] and bool(result["has_prefix"])
        if not ok:
            failures += 1
        print(
            f"[{'PASS' if ok else 'FAIL'}] {kind} {question}\n"
            f"  refused={result['refused']} reason={result['refusal_reason']} "
            f"prefix={result['has_prefix']} suggestions={result['suggestions']} "
            f"valid={result['valid']} invalid={result['invalid']} "
            f"uncited={result['uncited']} conversation={result['conversation_id']} "
            f"message={result['message_id']}"
        )

    print(f"\n结果：{len(rows) - failures}/{len(rows)} 通过")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())