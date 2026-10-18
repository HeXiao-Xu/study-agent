"""S1-2 演示：解析→切片→逐块摘要 + token 分布直方图（任务卡验收）。

用法（仓库根目录）：
    python scripts/chunk_demo.py <文件> [--limit 30] [--force-pymupdf]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.ai.parse import parse_document  # noqa: E402
from app.ai.rag.chunker import chunk_document  # noqa: E402


def histogram(tokens: list[int]) -> str:
    buckets = [(0, 100), (101, 200), (201, 300), (301, 400), (401, 500),
               (501, 600), (601, 700), (701, 800), (801, 10**9)]
    lines = []
    for lo, hi in buckets:
        n = sum(1 for t in tokens if lo <= t <= hi)
        bar = "█" * min(n, 40)
        label = f">{lo - 1}" if hi == 10**9 else f"{lo}-{hi}"
        lines.append(f"{label:>8} | {bar} {n}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="结构化切片演示（S1-2）")
    parser.add_argument("file", help="PDF/DOCX 文件路径")
    parser.add_argument("--limit", type=int, default=30, help="打印前 N 块（默认 30）")
    parser.add_argument("--force-pymupdf", action="store_true", help="解析走快速路径")
    args = parser.parse_args()

    doc = parse_document(args.file, force_pymupdf=args.force_pymupdf)
    chunks = chunk_document(doc)
    questions = [c for c in chunks if c.chunk_type.value == "question"]
    print(f"文件: {doc.source}    解析器: {doc.parser}    块数: {len(chunks)}（question {len(questions)}）")
    print("-" * 72)
    for c in chunks[: args.limit]:
        print(f"[{c.chunk_index}] ({c.chunk_type.value}) {c.token_count}t p.{c.page_no}「{c.heading_path}」")
        text = c.content.replace("\n", " ")
        print(f"    {text[:70]}{'…' if len(text) > 70 else ''}")
    print("-" * 72)
    print("token 分布直方图：")
    print(histogram([c.token_count for c in chunks]))
    if chunks:
        avg = sum(c.token_count for c in chunks) / len(chunks)
        print(f"均值 {avg:.0f} token / 块")
    return 0


if __name__ == "__main__":
    sys.exit(main())
