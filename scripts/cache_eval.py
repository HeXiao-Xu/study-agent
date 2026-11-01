"""S3-7 真实缓存验收：同一问题连续问两次，第二次必须零 LLM 调用。

用法：
    python scripts/cache_eval.py --user-id 18
    python scripts/cache_eval.py --user-id 18 --question "错位相减法怎么用？"
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import func, select  # noqa: E402

from app.core.cache import get_cache  # noqa: E402
from app.core.context import (  # noqa: E402
    reset_current_user_id,
    set_current_user_id,
    set_trace_id,
)
from app.core.db import new_session  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.models.llm_call_log import LLMCallLog  # noqa: E402
from app.services import qa_cache_service, qa_service  # noqa: E402


def _count_logs(session) -> int:
    return int(session.scalar(select(func.count()).select_from(LLMCallLog)) or 0)


def _one_ask(session, *, user_id: int, question: str) -> tuple[float, dict, str]:
    started = time.perf_counter()
    plan = qa_service.prepare_ask(
        session,
        user_id=user_id,
        question=question,
        scope=None,
        conversation_id=None,
    )
    events = list(qa_service.stream_events(plan))
    elapsed = time.perf_counter() - started
    done = next(
        (event.data for event in reversed(events) if event.event == "done"),
        None,
    )
    if done is None:
        error = next(
            (event.data for event in events if event.event == "error"), None
        )
        raise SystemExit(f"问答失败：{error or '没有 done 事件'}")
    text = "".join(
        str(event.data.get("text", ""))
        for event in events
        if event.event == "delta"
    )
    print(
        "  SSE 事件：",
        [event.event for event in events],
        "delta 文本：",
        text[:120],
    )
    return elapsed, done, text


def run(*, user_id: int, question: str) -> None:
    cache = get_cache()
    cache_key = qa_cache_service.cache_key(user_id, question, None)
    # 保证验收从 miss 开始；生产 TTL 不受影响。
    cache.delete(cache_key)

    user_token = set_current_user_id(user_id)
    set_trace_id(f"cache-eval-{uuid.uuid4().hex[:12]}")
    try:
        with new_session() as session:
            baseline = _count_logs(session)

            print("第一问（预期 miss）")
            first_elapsed, first_done, first_text = _one_ask(
                session, user_id=user_id, question=question
            )
            after_first = _count_logs(session)
            first_calls = after_first - baseline
            cached_value = qa_cache_service.get(
                cache, user_id=user_id, question=question, scope=None
            )
            print(
                json.dumps(
                    {
                        "elapsed_ms": round(first_elapsed * 1000),
                        "cached": first_done["cached"],
                        "tokens": first_done["tokens"],
                        "new_llm_call_logs": first_calls,
                        "cache_written": cached_value is not None,
                    },
                    ensure_ascii=False,
                )
            )

            print("第二问（预期 hit）")
            second_elapsed, second_done, second_text = _one_ask(
                session, user_id=user_id, question=question
            )
            second_calls = _count_logs(session) - after_first
            print(
                json.dumps(
                    {
                        "elapsed_ms": round(second_elapsed * 1000),
                        "cached": second_done["cached"],
                        "tokens": second_done["tokens"],
                        "new_llm_call_logs": second_calls,
                        "answer_same": second_text == first_text,
                        "new_message_id": second_done["message_id"]
                        != first_done["message_id"],
                    },
                    ensure_ascii=False,
                )
            )

            failures: list[str] = []
            if first_calls <= 0:
                failures.append("第一问没有产生 llm_call_logs，无法证明 miss")
            if cached_value is None:
                failures.append("第一问后 Redis 中没有缓存载荷")
            if first_done["cached"] is not False:
                failures.append("第一问 cached 应为 false")
            if second_calls != 0:
                failures.append(f"第二问新增调用日志 {second_calls} 条，应为 0")
            if second_done["cached"] is not True:
                failures.append("第二问 cached 应为 true")
            if int(second_done["tokens"]) != 0:
                failures.append("第二问 tokens 应为 0")
            if second_text != first_text:
                failures.append("第二问答案与第一问不一致")
            if second_done["message_id"] == first_done["message_id"]:
                failures.append("第二问没有落新的 assistant 消息")
            if second_elapsed >= first_elapsed:
                failures.append(
                    f"第二问未更快：{second_elapsed:.3f}s >= {first_elapsed:.3f}s"
                )
            if failures:
                raise SystemExit("验收失败：\n- " + "\n- ".join(failures))
            print("验收通过：第二问命中缓存、零新增调用、tokens=0。")
    finally:
        reset_current_user_id(user_token)


def main() -> None:
    parser = argparse.ArgumentParser(description="S3-7 缓存真实验收")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument(
        "--question", default="错位相减法怎么用？", help="需在真实笔记中有依据"
    )
    args = parser.parse_args()
    setup_logging()
    run(user_id=args.user_id, question=args.question)


if __name__ == "__main__":
    main()