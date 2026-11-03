"""S4-5 图谱构建 CLI：本机直接跑（不进队列），便于验收与调试。

用法：
  ..\\.venv\\Scripts\\python.exe scripts\\build_graph.py --subject 7
  ..\\.venv\\Scripts\\python.exe scripts\\build_graph.py --subject 7 --relations prerequisite --limit 5 --dry-run
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import new_session  # noqa: E402
from app.services import graph_service  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="构建知识图谱关系边")
    parser.add_argument("--subject", type=int, required=True, help="学科 id")
    parser.add_argument(
        "--relations",
        default="",
        help="逗号分隔：contains,prerequisite,related,confusable（默认全部）",
    )
    parser.add_argument("--limit", type=int, default=None, help="只推断前 N 个节点的前置")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args()

    relations = [item.strip() for item in args.relations.split(",") if item.strip()]
    with new_session() as session:
        summary = graph_service.build(
            session,
            subject_id=args.subject,
            relations=relations or None,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            session.commit()
    for key, value in asdict(summary).items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())