"""S6-1 schema 导出：11 条 OpenAI function + 仓库文件不漂移。"""
from __future__ import annotations

import json
from pathlib import Path

from app.ai.agents.tools.schema_export import build_export_payload, dumps_payload


def test_export_payload_has_11_openai_functions():
    payload = build_export_payload()
    assert payload["version"] == 1
    assert len(payload["tools"]) == 11
    names = [item["function"]["name"] for item in payload["tools"]]
    assert names == [
        "search_notes",
        "list_notes",
        "get_kp_subgraph",
        "list_mistakes",
        "get_mastery",
        "search_questions",
        "generate_questions",
        "make_mindmap",
        "create_review_plan",
        "export_paper_pdf",
        "calculator",
    ]
    for item in payload["tools"]:
        function = item["function"]
        assert item["type"] == "function"
        assert function["description"]
        assert function["parameters"]["type"] == "object"
        assert function["parameters"]["additionalProperties"] is False
    assert set(payload["outputs"]) == set(names)


def test_committed_schema_file_matches_generator():
    path = Path(__file__).resolve().parents[1] / "data" / "agent_tools.json"
    assert path.read_text(encoding="utf-8") == dumps_payload(build_export_payload())


def test_schema_is_valid_json_with_tool_parameters():
    payload = json.loads(dumps_payload(build_export_payload()))
    calculator = next(
        item["function"] for item in payload["tools"] if item["function"]["name"] == "calculator"
    )
    assert "expression" in calculator["parameters"]["properties"]
    assert calculator["parameters"]["required"] == ["expression"]