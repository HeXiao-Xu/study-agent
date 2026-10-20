"""S1-6 脚本冒烟：只跑 --help，不连库、不调外部 API。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_s1_6_scripts_help() -> None:
    for name in ("ask.py", "calibrate_refusal.py"):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / name), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, f"{name}: {result.stderr}"
        assert "usage" in result.stdout.lower() or "用法" in result.stdout