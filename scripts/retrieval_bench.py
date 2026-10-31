"""S3-2 检索接口压测：HTTP 端到端、默认关闭重排，输出 P50/P95。

用法（仓库根目录，需 uvicorn 已启动）：
    .\.venv\Scripts\python.exe scripts/retrieval_bench.py \
        --username test1 --password *** --runs 20 --warmup 3 --no-rerank

口径：wall_ms 含网络+服务端；server_ms 取响应 data.elapsed_ms（含查询 Embedding）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

QUESTIONS = Path("eval/datasets/qa_set.jsonl")


def _configure_stdio() -> None:
    """Windows 控制台默认 GBK；问题含中文，统一转 UTF-8 防 print 崩溃。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _load_questions(limit: int) -> list[str]:
    rows = [
        json.loads(line)
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    questions = [row["question"] for row in rows]
    if len(questions) < limit:
        raise ValueError(f"问题不足：需要 {limit}，实际 {len(questions)}")
    return questions[:limit]


def _percentile(values: list[int], ratio: float) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


def _login(client: httpx.Client, base_url: str, username: str, password: str) -> str:
    response = client.post(
        f"{base_url}/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    response.raise_for_status()
    return response.json()["data"]["access_token"]


def _search(
    client: httpx.Client,
    base_url: str,
    token: str,
    question: str,
    *,
    top_k: int,
    rerank: bool,
) -> tuple[int, int, int]:
    started = time.perf_counter()
    response = client.post(
        f"{base_url}/api/v1/retrieval/search",
        json={"query": question, "top_k": top_k, "rerank": rerank},
        headers={"Authorization": f"Bearer {token}"},
    )
    wall_ms = int((time.perf_counter() - started) * 1000)
    response.raise_for_status()
    data = response.json()["data"]
    return wall_ms, int(data["elapsed_ms"]), int(data["embedding_ms"])


def main() -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="S3-2 检索接口 P50/P95 压测")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--no-rerank", action="store_true", help="关闭重排（验收口径）")
    args = parser.parse_args()
    if args.runs <= 0 or args.warmup < 0:
        parser.error("--runs 必须 >0，--warmup 必须 >=0")

    questions = _load_questions(max(args.runs, args.warmup, 1))
    rerank = not args.no_rerank

    with httpx.Client(timeout=60.0) as client:
        token = _login(client, args.base_url, args.username, args.password)
        for index in range(args.warmup):
            _search(
                client,
                args.base_url,
                token,
                questions[index % len(questions)],
                top_k=args.top_k,
                rerank=rerank,
            )

        walls: list[int] = []
        servers: list[int] = []
        embeds: list[int] = []
        print(f"{'#':>3} {'wall_ms':>8} {'server_ms':>10} {'embedding_ms':>13}  question")
        for index in range(args.runs):
            question = questions[index % len(questions)]
            wall, server, embedding = _search(
                client,
                args.base_url,
                token,
                question,
                top_k=args.top_k,
                rerank=rerank,
            )
            walls.append(wall)
            servers.append(server)
            embeds.append(embedding)
            print(f"{index + 1:>3} {wall:>8} {server:>10} {embedding:>13}  {question}")

    p50 = _percentile(walls, 0.50)
    p95 = _percentile(walls, 0.95)
    s_p50 = _percentile(servers, 0.50)
    s_p95 = _percentile(servers, 0.95)
    e_p50 = _percentile(embeds, 0.50)
    print(
        f"\nwall   P50={p50}ms P95={p95}ms\n"
        f"server P50={s_p50}ms P95={s_p95}ms  (含查询 Embedding)\n"
        f"embed  P50={e_p50}ms\n"
        f"rerank={rerank} runs={args.runs} warmup={args.warmup}"
    )
    target = 500
    print(f"P95 目标 < {target}ms：{'PASS' if p95 < target else 'FAIL'}")
    return 0 if p95 < target else 2


if __name__ == "__main__":
    sys.exit(main())