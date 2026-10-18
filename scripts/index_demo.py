"""S1-3 演示：解析 → 切片 → 探测维度 → 批量向量化 → pgvector 入库。

用法（仓库根目录）：
    python scripts/index_demo.py <文件> [--note-id 1] [--user-id 1]
           [--source-file-id N] [--force-pymupdf] [--probe-only] [--no-replace]
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy.exc import OperationalError  # noqa: E402

from app.ai.embedding import BatchStats, get_embedding_client  # noqa: E402
from app.ai.embedding.errors import EmbeddingError  # noqa: E402
from app.ai.parse import parse_document  # noqa: E402
from app.ai.rag.chunker import chunk_document  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.context import set_trace_id  # noqa: E402
from app.core.db import new_session  # noqa: E402
from app.services.indexing import index_chunks  # noqa: E402

_ACCEPTANCE_SQL = """
验收 SQL（在仓库根目录执行）：
  docker exec study-agent-postgres psql -U study -d study_agent -c "SELECT count(*) FROM note_chunks;"
  docker exec study-agent-postgres psql -U study -d study_agent -c "SELECT heading_path, left(content,30) FROM note_chunks LIMIT 5;"
  docker exec study-agent-postgres psql -U study -d study_agent -c "SELECT left(content,60) FROM note_chunks WHERE tsv @@ to_tsquery('simple','函数 & 单调性') LIMIT 3;"
"""


def _print_progress(stats: BatchStats) -> None:
    print(
        f"  [batch {stats.batch_index + 1}/{stats.batch_count}] "
        f"{stats.batch_size} 条 · {stats.tokens} tokens · {stats.latency_ms} ms"
    )


def _probe(client) -> int:
    settings = get_settings()
    vector = client.encode(["维度探测：函数的单调性"])[0]
    print(f"Embedding 实测：model={client.model} 维度={len(vector)}（配置 {settings.embedding_dim}）")
    if len(vector) != settings.embedding_dim:
        print(
            "维度与配置/SCHEMA 不一致，停止。请报告契约冲突，不要自行改表（spec §4.4）。",
            file=sys.stderr,
        )
        return 4
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Embedding 与 pgvector 入库演示（S1-3）")
    parser.add_argument("file", help="PDF/DOCX 文件路径")
    parser.add_argument("--note-id", type=int, default=1, help="合成笔记 ID（S2-1 前无 notes 表）")
    parser.add_argument("--user-id", type=int, default=1, help="合成用户 ID")
    parser.add_argument("--source-file-id", type=int, default=None, help="合成来源文件 ID")
    parser.add_argument("--force-pymupdf", action="store_true", help="解析走快速路径")
    parser.add_argument("--probe-only", action="store_true", help="只探测向量维度，不写库")
    parser.add_argument("--no-replace", action="store_true", help="不删除同 note_id 的旧块")
    args = parser.parse_args()

    set_trace_id("index-" + uuid.uuid4().hex[:12])
    try:
        client = get_embedding_client()
    except EmbeddingError as exc:
        print(f"Embedding 未就绪：{exc}", file=sys.stderr)
        return 2
    if args.probe_only:
        try:
            return _probe(client)
        except EmbeddingError as exc:
            print(f"Embedding 调用失败：{exc}", file=sys.stderr)
            return 2

    doc = parse_document(args.file, force_pymupdf=args.force_pymupdf)
    chunks = chunk_document(doc)
    questions = sum(1 for chunk in chunks if chunk.chunk_type.value == "question")
    print(
        f"文件: {doc.source}    解析器: {doc.parser}    "
        f"块数: {len(chunks)}（question {questions}）"
    )
    if not chunks:
        print("没有可入库的切片（扫描版/空文档），退出。")
        return 0

    try:
        with new_session() as session:
            result = index_chunks(
                session,
                chunks,
                note_id=args.note_id,
                user_id=args.user_id,
                source_file_id=args.source_file_id,
                replace=not args.no_replace,
                client=client,
                progress=_print_progress,
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

    print("-" * 72)
    print(
        f"入库完成：{result.chunk_count} 块 · 维度 {result.vector_dim} · "
        f"{result.total_tokens} tokens · {result.elapsed_ms} ms · "
        f"估算花费 ¥{result.cost_cny:.6f}"
    )
    print(_ACCEPTANCE_SQL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
