"""把 Agent 工具 schema 导出为 JSON（供 LLM function calling 与 S6-2 使用）。

用法（仓库根目录）：
    python scripts/export_agent_tools.py
    python scripts/export_agent_tools.py --out backend/data/agent_tools.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.ai.agents.tools.schema_export import (  # noqa: E402
    build_export_payload,
    dumps_payload,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out", default=str(ROOT / "backend" / "data" / "agent_tools.json")
    )
    args = parser.parse_args()
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dumps_payload(build_export_payload()), encoding="utf-8")
    print(f"已写入 {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())