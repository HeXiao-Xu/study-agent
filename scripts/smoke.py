"""S0-7 冒烟自检：一条命令验证「整个开发环境是否 OK」。

用法（仓库根目录，任何位置的 python 均可——零第三方依赖）：
    python scripts/smoke.py

检查项（顺序执行，彩色清单，退出码非 0 = 有失败）：
  1-3  Postgres / Redis / MinIO 连通（复用 check_services，不重复实现）
  4    pgvector 扩展已启用
  5    MinIO bucket 已创建
  6    后端 /health 可访问且符合统一响应壳
  7    核心业务表（当前阶段无表属预期，不判失败；S2-1 起填 REQUIRED_TABLES）
  8    前端 dev server（可选组件：未启动记 SKIP，不判失败）

为什么数据库检查用 docker exec psql 而不是 Python 驱动：
venv 尚未安装 SQLAlchemy/psycopg 的阶段也要能自检；且能证明
「三件套容器里的数据库」可用，而不只是「某个数据库」可达。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

# 同目录导入 check_services（sys.path 注入后任意启动目录都可用）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_services import _cfg, check_minio, check_postgres, check_redis  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
# 前端必须用主机名而非 127.0.0.1：vite 默认绑 localhost，Node 17+ 常解析为 IPv6 (::1)，
# 硬写 IPv4 会"端口在监听却连不上"
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")

# S2-1 起随迁移维护：核心业务表名；非空时缺任何一张判 FAIL（提示先执行迁移）
REQUIRED_TABLES: list[str] = []

# Windows 旧式控制台需先激活 ANSI 转义（空命令，无副作用）
if os.name == "nt":
    os.system("")

GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def _env(name: str, default: str) -> str:
    """读环境变量（.env 已由 _load_dotenv 注入），缺省回落开发默认值。"""
    return os.environ.get(name, default)


def _load_dotenv() -> None:
    """把根目录 .env 读进环境（setdefault 不覆盖真实变量），尊重用户改过的账号/库名/桶名。"""
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _psql(query: str) -> str:
    """在 postgres 容器内执行 SQL 并返回 stdout（-tAc：只输出单值）。"""
    cmd = [
        "docker", "exec", "study-agent-postgres",
        "psql", "-U", _env("POSTGRES_USER", "study"), "-d", _env("POSTGRES_DB", "study_agent"),
        "-tAc", query,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"docker exec 失败（容器没起或引擎未运行）: {proc.stderr.strip()[:100]}")
    return proc.stdout.strip()


def check_pg_extension() -> str:
    out = _psql("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    if out != "1":
        raise RuntimeError("扩展未启用；若重建过数据卷，按 deploy/initdb/01-extensions.sql 内注释补建")
    return "vector 扩展已启用"


def check_bucket() -> str:
    """匿名探测：401/403 = 桶存在（只是禁止匿名列举），404 = 桶不存在。"""
    bucket = _env("MINIO_BUCKET", "study-agent")
    url = f"http://{_cfg('MINIO_HOST')}:{_cfg('MINIO_PORT')}/{bucket}/"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    if status in (401, 403):
        return f"bucket '{bucket}' 存在"
    if status == 404:
        raise RuntimeError(f"bucket '{bucket}' 不存在；重跑 compose 由 minio-init 自动建桶")
    raise RuntimeError(f"非预期 HTTP {status}")


def check_backend() -> str:
    """比 curl 更严：校验统一响应壳语义（docs/API.md §0）。"""
    try:
        with urllib.request.urlopen(f"{BACKEND_URL}/health", timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"连不上（{exc.reason}）；启动：cd backend && uvicorn app.main:app --reload"
        ) from exc
    data = body.get("data") or {}
    if body.get("code") != 0 or data.get("status") != "ok":
        raise RuntimeError(f"响应不符合统一壳: {body}")
    return f"/health 正常（{data.get('app')} v{data.get('version')}）"


def check_tables() -> tuple[str, str]:
    """返回 (status, detail)。判定规则见模块 docstring 第 7 条。"""
    if REQUIRED_TABLES:
        missing = [
            t for t in REQUIRED_TABLES
            if _psql(
                "SELECT 1 FROM information_schema.tables "
                f"WHERE table_schema='public' AND table_name='{t}'"
            ) != "1"
        ]
        if missing:
            return FAIL, f"缺核心表 {missing} —— 请先执行迁移（Alembic，S2-1）"
        return PASS, f"核心表 {len(REQUIRED_TABLES)}/{len(REQUIRED_TABLES)} 在位"
    count = int(_psql(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='BASE TABLE'"
    ))
    if count == 0:
        return PASS, "无业务表（当前阶段预期；迁移 S2-1 起交付）"
    return PASS, f"已有 {count} 张表"


def check_frontend() -> str | None:
    """前端 dev 为可选组件：连不上返回 None → 记 SKIP 不判失败。"""
    try:
        with urllib.request.urlopen(FRONTEND_URL, timeout=3) as resp:
            if resp.status == 200:
                return "dev server 在跑"
    except Exception:  # noqa: BLE001 —— 任何连接失败都按「未启动」处理
        return None
    return None


def _report(idx: int, total: int, name: str, status: str, detail: str) -> None:
    color = {PASS: GREEN, FAIL: RED, SKIP: YELLOW}[status]
    print(f"[{idx}/{total}] {color}{status}{RESET}  {name}：{detail}")


def main() -> int:
    _load_dotenv()
    print(f"study-agent 冒烟自检  后端={BACKEND_URL}  前端={FRONTEND_URL}")
    print("-" * 62)

    steps: list[tuple[str, Callable[[], str]]] = [
        ("Postgres 连通", lambda: check_postgres(_cfg("POSTGRES_HOST"), int(_cfg("POSTGRES_PORT")))),
        ("Redis 连通", lambda: check_redis(_cfg("REDIS_HOST"), int(_cfg("REDIS_PORT")))),
        ("MinIO 连通", lambda: check_minio(_cfg("MINIO_HOST"), int(_cfg("MINIO_PORT")))),
        ("pgvector 扩展", check_pg_extension),
        ("MinIO bucket", check_bucket),
        ("后端 /health", check_backend),
    ]
    total = len(steps) + 2  # + 业务表 + 前端（可选）

    failed = 0
    skipped = 0
    postgres_ok = False

    for i, (name, fn) in enumerate(steps, start=1):
        try:
            detail = fn()
        except Exception as exc:  # noqa: BLE001 —— 冒烟必须把失败原因原样打出
            detail = str(exc)
            status = FAIL
            failed += 1
        else:
            status = PASS
        if name == "Postgres 连通":
            postgres_ok = status == PASS
        _report(i, total, name, status, detail)

    # 业务表（依赖 Postgres；未连上时跳过以免重复报错刷屏）
    idx = len(steps) + 1
    if not postgres_ok:
        _report(idx, total, "业务表", SKIP, "Postgres 未连上，跳过")
        skipped += 1
    else:
        try:
            status, detail = check_tables()
        except Exception as exc:  # noqa: BLE001
            status, detail = FAIL, str(exc)
        if status == FAIL:
            failed += 1
        _report(idx, total, "业务表", status, detail)

    # 前端（可选组件）
    idx += 1
    detail = check_frontend()
    if detail is None:
        _report(idx, total, "前端 dev", SKIP, "未启动（可选；启动：cd web && npm run dev）")
        skipped += 1
    else:
        _report(idx, total, "前端 dev", PASS, detail)

    print("-" * 62)
    passed = total - failed - skipped
    print(f"结论：{passed} 通过 / {failed} 失败 / {skipped} 跳过")
    if failed:
        print(f"{RED}环境未就绪：处理上方 FAIL 项后重跑 python scripts/smoke.py{RESET}")
        return 1
    print(f"{GREEN}环境就绪（m0-env-ready）{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
