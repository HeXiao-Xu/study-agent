"""S0-4 基础服务连通性自检：Postgres / Redis / MinIO。

用法（仓库根目录）：
    python scripts/check_services.py

设计说明（为什么只用标准库）：
- 本脚本必须在“后端依赖尚未安装”的 S0-4 阶段就能直接运行（AGENTS.md：不引入未经确认的依赖）；
- Postgres 用协议层握手（SSLRequest）验证，Redis 用 PING/PONG，MinIO 用官方健康端点；
- S0-7 的 smoke.py 将升级为完整冒烟检查（pgvector 扩展、后端 /health、关键表存在性）。
"""

from __future__ import annotations

import os
import socket
import sys
import urllib.request

# 与 deploy/docker-compose.dev.yml、.env.example 的默认值保持一致
DEFAULTS = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "REDIS_HOST": "localhost",
    "REDIS_PORT": "6379",
    "MINIO_HOST": "localhost",
    "MINIO_PORT": "9000",
}


def _cfg(name: str) -> str:
    """读环境变量，缺省回落到 compose 的开发默认值。"""
    return os.environ.get(name, DEFAULTS[name])


def check_postgres(host: str, port: int) -> str:
    """协议层握手：发送 SSLRequest（length=8, code=80877103）。

    为什么不用 SELECT 1：那需要驱动与认证，而 S0-4 阶段 venv 里没有任何依赖；
    收到 N（不支持 SSL）或 S（支持 SSL）任一应答即证明对面是活着的 Postgres。
    """
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.sendall((8).to_bytes(4, "big") + (80877103).to_bytes(4, "big"))
        resp = sock.recv(1)
    if resp in (b"N", b"S"):
        return "OK - 协议应答正常（扩展/建表检查见 S0-7 smoke）"
    raise RuntimeError(f"非预期的协议应答: {resp!r}")


def check_redis(host: str, port: int) -> str:
    """PING/PONG。开发环境 Redis 未设密码；将来设密码需先 AUTH（届时再改本函数）。"""
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.settimeout(5)
        sock.sendall(b"PING\r\n")
        resp = sock.recv(64)
    if resp.startswith(b"+PONG"):
        return "OK - PING/PONG 正常"
    raise RuntimeError(f"非预期应答: {resp!r}")


def check_minio(host: str, port: int) -> str:
    """官方健康端点 /minio/health/live 无需认证，200 即存活。"""
    url = f"http://{host}:{port}/minio/health/live"
    with urllib.request.urlopen(url, timeout=5) as resp:
        if resp.status == 200:
            return "OK - /minio/health/live 返回 200"
    raise RuntimeError("健康端点未返回 200")


def main() -> int:
    checks = [
        ("Postgres", check_postgres, _cfg("POSTGRES_HOST"), int(_cfg("POSTGRES_PORT"))),
        ("Redis", check_redis, _cfg("REDIS_HOST"), int(_cfg("REDIS_PORT"))),
        ("MinIO", check_minio, _cfg("MINIO_HOST"), int(_cfg("MINIO_PORT"))),
    ]
    passed = 0
    for i, (name, fn, host, port) in enumerate(checks, start=1):
        try:
            msg = fn(host, port)
            passed += 1
            print(f"[{i}/{3}] {name:<8} ({host}:{port}) {msg}")
        except Exception as exc:  # noqa: BLE001 —— 自检脚本必须把失败原因原样打出来
            print(f"[{i}/{3}] {name:<8} ({host}:{port}) 失败 - {exc}")
    verdict = "全部通过" if passed == 3 else "存在失败项，看上方原因"
    print(f"结论：{passed}/3 通过，{verdict}")
    return 0 if passed == 3 else 1


if __name__ == "__main__":
    sys.exit(main())
