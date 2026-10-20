"""S1-6 带引用问答 CLI。

用法：
    python scripts/ask.py "我笔记里关于错位相减法是怎么总结的？"
    python scripts/ask.py --user-id 1 "今天北京天气怎么样？"
    python scripts/ask.py          # 交互循环
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy.exc import OperationalError  # noqa: E402

from app.ai.embedding.errors import EmbeddingError  # noqa: E402
from app.ai.llm.errors import LLMError  # noqa: E402
from app.ai.rag.answerer import AnswerResult, answer_question  # noqa: E402
from app.ai.rag.prompt_builder import Citation, PromptTemplateError  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.context import set_trace_id  # noqa: E402
from app.core.db import new_session  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402


def _configure_stdio() -> None:
    """Windows 控制台默认 GBK；答案里的公式/¥ 可能超出 GBK，统一 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, OSError):
                pass


def _format_citation(citation: Citation) -> str:
    source = (
        f"文件 #{citation.source_file_id}"
        if citation.source_file_id is not None
        else "文件未知"
    )
    page = (
        f"第 {citation.page_no} 页"
        if citation.page_no is not None
        else "页码未知"
    )
    heading = citation.heading_path or "章节未标注"
    return (
        f"[{citation.index}] 笔记 #{citation.note_id} / {source} / "
        f"{page} / 章节：{heading}"
    )


def _print_result(question: str, result: AnswerResult, *, debug: bool) -> None:
    print(f"问题：{question}")
    print("回答：")
    print(result.answer)
    if result.citations:
        print("\n引用：")
        for citation in result.citations:
            print(_format_citation(citation))
            print(f"    片段：{citation.snippet.replace(chr(10), ' ')[:160]}")
    if debug:
        print(
            f"\n调试：refused={result.refused} reason={result.refusal_reason} "
            f"degraded={result.degraded} top_score={result.top_rerank_score} "
            f"context_tokens={result.context_tokens} llm_calls={result.llm_calls}"
        )
    print(
        f"\n统计：refused={'是' if result.refused else '否'} "
        f"reason={result.refusal_reason or '无'} llm_calls={result.llm_calls} "
        f"tokens={result.prompt_tokens}/{result.completion_tokens}/{result.total_tokens} "
        f"latency=retrieval {result.retrieval_ms}ms + llm {result.llm_ms}ms "
        f"= {result.latency_ms}ms "
        f"cost=¥{result.cost_yuan:.6f}"
    )


def _ask_one(
    question: str,
    *,
    user_id: int,
    top_k: int,
    threshold: float | None,
    debug: bool,
) -> int:
    try:
        with new_session() as session:
            result = answer_question(
                session,
                question,
                user_id=user_id,
                top_k=top_k,
                threshold=threshold,
            )
            _print_result(question, result, debug=debug)
            return 0
    except LLMError as exc:
        print(f"LLM 调用失败：{exc}", file=sys.stderr)
        return 2
    except PromptTemplateError as exc:
        print(f"Prompt 模板错误：{exc}", file=sys.stderr)
        return 3
    except OperationalError:
        print(
            "数据库连接失败：请先启动基础服务 "
            "docker compose -f deploy/docker-compose.dev.yml up -d",
            file=sys.stderr,
        )
        return 4
    except EmbeddingError as exc:
        print(f"Embedding 调用失败：{exc}", file=sys.stderr)
        return 5


def main() -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="S1-6 带引用问答 CLI")
    parser.add_argument("question", nargs="?", help="问题；不传则进入交互循环")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level, stream=sys.stderr)
    set_trace_id("qa-" + uuid.uuid4().hex[:12])

    if args.question:
        return _ask_one(
            args.question,
            user_id=args.user_id,
            top_k=args.top_k,
            threshold=args.threshold,
            debug=args.debug,
        )

    last_code = 0
    while True:
        try:
            question = input("问题（exit 退出）> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return last_code
        if question.lower() in {"exit", "quit"}:
            return last_code
        if not question:
            continue
        last_code = _ask_one(
            question,
            user_id=args.user_id,
            top_k=args.top_k,
            threshold=args.threshold,
            debug=args.debug,
        )


if __name__ == "__main__":
    sys.exit(main())