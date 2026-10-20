"""评测脚本的 Windows 控制台编码回归：内容里的 ✗ 不能把输出打崩。"""
from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
from types import ModuleType


def _load_eval_module() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "retrieval_eval.py"
    spec = importlib.util.spec_from_file_location("retrieval_eval_for_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_configure_stdio_outputs_utf8_symbols() -> None:
    module = _load_eval_module()
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="gbk")

    with contextlib.redirect_stdout(stream):
        module._configure_stdio()
        print("✗")
        stream.flush()

    assert raw.getvalue().decode("utf-8").strip() == "✗"