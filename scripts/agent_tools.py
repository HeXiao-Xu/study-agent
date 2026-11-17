"""S6-1 Agent 工具 CLI：列出工具、打印 schema、用真实库调用单个工具。

用法（仓库根目录）：
    python scripts/agent_tools.py list
    python scripts/agent_tools.py schema
    python scripts/agent_tools.py call --user-id 50 calculator '{"expression":"1/3"}'
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.ai.agents.tools import TOOL_ORDER, TOOLS, ToolContext, invoke_tool  # noqa: E402
from app.ai.agents.tools.schema_export import (  # noqa: E402
    build_export_payload,
    dumps_payload,
)
from app.core.db import new_session  # noqa: E402
from app.core.exceptions import AppError  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.models.user import User  # noqa: E402


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, OSError):
                pass


def _cmd_list() -> int:
    for name in TOOL_ORDER:
        first = TOOLS[name].description.split("。")[0]
        print(f"{name}\t{first}。")
    return 0


def _cmd_schema() -> int:
    print(dumps_payload(build_export_payload()), end="")
    return 0


def _cmd_call(args: argparse.Namespace) -> int:
    setup_logging()
    try:
        payload = json.loads(args.payload)
    except json.JSONDecodeError as exc:
        print(f"参数不是合法 JSON：{exc}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("参数必须是 JSON 对象", file=sys.stderr)
        return 2
    with new_session() as session:
        user = session.get(User, args.user_id)
        if user is None:
            print(f"用户不存在：{args.user_id}", file=sys.stderr)
            return 2
        try:
            out = invoke_tool(
                args.tool, ToolContext(session=session, user=user), payload
            )
        except AppError as exc:
            print(f"{exc.code}\t{exc.message}", file=sys.stderr)
            return 1
    print(out.model_dump_json(indent=2))
    return 0


def main() -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="S6-1 Agent 工具 CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="列出全部工具")
    sub.add_parser("schema", help="打印 OpenAI function-calling schema")
    call = sub.add_parser("call", help="用真实库调用一个工具")
    call.add_argument("--user-id", type=int, required=True)
    call.add_argument("tool")
    call.add_argument("payload")
    args = parser.parse_args()
    if args.command == "list":
        return _cmd_list()
    if args.command == "schema":
        return _cmd_schema()
    return _cmd_call(args)


if __name__ == "__main__":
    raise SystemExit(main())