"""S4-5 CLI 冒烟：参数解析可用（不连库、不调 LLM）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_cli_help_runs():
    result = subprocess.run(
        [sys.executable, str(BACKEND / "scripts" / "build_graph.py"), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert result.returncode == 0
    assert "--dry-run" in result.stdout
    assert "--relations" in result.stdout