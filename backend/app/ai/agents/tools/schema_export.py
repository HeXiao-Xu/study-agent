"""S6-1 schema 导出：OpenAI function-calling 兼容结构（可重复生成）。"""
from __future__ import annotations

import json
from typing import Any


def build_export_payload() -> dict[str, Any]:
    from app.ai.agents.tools.registry import TOOLS, TOOL_ORDER

    tools = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": TOOLS[name].description,
                "parameters": TOOLS[name].input_model.model_json_schema(),
            },
        }
        for name in TOOL_ORDER
    ]
    outputs = {
        name: TOOLS[name].output_model.model_json_schema() for name in TOOL_ORDER
    }
    return {"version": 1, "tools": tools, "outputs": outputs}


def dumps_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"