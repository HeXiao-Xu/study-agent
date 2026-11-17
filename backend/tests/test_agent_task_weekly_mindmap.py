"""S6-3 weekly_mindmap：日期窗口、三阶段扩展、摘要/引用/空窗口/降级。"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.ai.agents.tasks.weekly_mindmap import WeeklyMindmapTaskSpec
from app.core.exceptions import InvalidParamError

NOW = datetime(2026, 11, 17, 6, 0, tzinfo=timezone.utc)


def _notes_artifact(notes):  # noqa: ANN001
    return {"step_1": {"tool": "list_notes", "input": {}, "output": {"items": notes}}}


def test_validate_input_and_build_plan_window():
    data = WeeklyMindmapTaskSpec.validate_input({"days": 7})
    spec = WeeklyMindmapTaskSpec(data, now=NOW)
    assert spec.build_plan({})[0]["tool"] == "list_notes"
    payload = spec.build_plan({})[0]["input"]
    assert payload["start_date"] == "2026-11-11"
    assert payload["end_date"] == "2026-11-17"


def test_validate_input_rejects_bad_days():
    with pytest.raises(InvalidParamError):
        WeeklyMindmapTaskSpec.validate_input({"days": 0})
    with pytest.raises(InvalidParamError):
        WeeklyMindmapTaskSpec.validate_input({"days": 31})


def test_extend_prefers_top_three_kps():
    spec = WeeklyMindmapTaskSpec({"days": 7}, now=NOW)
    state = {
        "plan": [{"tool": "list_notes"}],
        "artifacts": _notes_artifact(
            [
                {"note_id": 1, "kp_ids": [11], "kp_names": ["A"], "title": "n1"},
                {"note_id": 2, "kp_ids": [11, 12], "kp_names": ["A", "B"], "title": "n2"},
                {"note_id": 3, "kp_ids": [13], "kp_names": ["C"], "title": "n3"},
            ]
        ),
    }
    ext = spec.extend_plan(state)
    assert [step["input"]["kp_id"] for step in ext.steps] == [11, 12, 13]
    assert all(step["tool"] == "get_kp_subgraph" for step in ext.steps)


def test_extend_builds_mindmap_after_subgraphs_with_llm():
    fake = SimpleNamespace(
        chat=lambda *a, **k: SimpleNamespace(
            text=(
                '{"title":"导图","branches":[{"kp_id":137,"title":"单调性",'
                '"conclusion":"复习了定义法。","note_ids":[54],"children":[]}]}'
            ),
            total_tokens=80,
        )
    )
    spec = WeeklyMindmapTaskSpec({"days": 7}, now=NOW, llm_client=fake)
    state = {
        "plan": [{"tool": "list_notes"}, {"tool": "get_kp_subgraph"}],
        "artifacts": {
            **_notes_artifact(
                [
                    {
                        "note_id": 54,
                        "title": "函数",
                        "kp_ids": [137],
                        "kp_names": ["单调性"],
                        "preview": "x",
                    }
                ]
            ),
            "step_2": {
                "tool": "get_kp_subgraph",
                "input": {"kp_id": 137},
                "output": {"nodes": [], "edges": []},
            },
        },
    }
    ext = spec.extend_plan(state)
    assert ext.token_cost == 80
    assert ext.steps[0]["tool"] == "make_mindmap"
    assert ext.steps[0]["input"]["nodes"][0]["name"] == "单调性"


def test_extend_without_kps_goes_straight_to_mindmap():
    fake = SimpleNamespace(
        chat=lambda *a, **k: SimpleNamespace(
            text=(
                '{"title":"导图","branches":[{"kp_id":null,"title":"笔记",'
                '"conclusion":"记录了两篇。","note_ids":[1],"children":[]}]}'
            ),
            total_tokens=10,
        )
    )
    spec = WeeklyMindmapTaskSpec({"days": 7}, now=NOW, llm_client=fake)
    state = {
        "plan": [{"tool": "list_notes"}],
        "artifacts": _notes_artifact(
            [{"note_id": 1, "title": "n1", "kp_ids": [], "kp_names": [], "preview": "x"}]
        ),
    }
    ext = spec.extend_plan(state)
    assert ext.steps[0]["tool"] == "make_mindmap"


def test_extend_degrades_when_cluster_fails():
    fake = SimpleNamespace(
        chat=lambda *a, **k: SimpleNamespace(text="不是 JSON", total_tokens=0)
    )
    spec = WeeklyMindmapTaskSpec({"days": 7}, now=NOW, llm_client=fake)
    state = {
        "plan": [{"tool": "list_notes"}, {"tool": "get_kp_subgraph"}],
        "artifacts": {
            **_notes_artifact(
                [
                    {
                        "note_id": 54,
                        "title": "函数",
                        "kp_ids": [137],
                        "kp_names": ["单调性"],
                        "preview": "x",
                    }
                ]
            ),
            "step_2": {
                "tool": "get_kp_subgraph",
                "input": {"kp_id": 137},
                "output": {"nodes": [], "edges": []},
            },
        },
    }
    ext = spec.extend_plan(state)
    assert ext.steps[0]["tool"] == "make_mindmap"
    assert spec.degraded is True
    assert "单调性" in str(ext.steps[0]["input"])


def test_empty_window_finalize_returns_empty_state():
    spec = WeeklyMindmapTaskSpec({"days": 7}, now=NOW)
    result = spec.finalize(
        {"plan": [{"tool": "list_notes"}], "artifacts": _notes_artifact([])}
    )
    assert result["note_count"] == 0
    assert result["mermaid"] == ""
    assert "没有笔记" in result["summary_md"]


def test_finalize_summary_and_citations_from_cluster():
    spec = WeeklyMindmapTaskSpec({"days": 7}, now=NOW)
    spec._cluster = SimpleNamespace(  # noqa: SLF001
        title="导图",
        branches=[
            SimpleNamespace(
                kp_id=137,
                title="单调性",
                conclusion="复习了定义法。",
                note_ids=[54],
                children=[],
            )
        ],
    )
    result = spec.finalize(
        {
            "plan": [{"tool": "make_mindmap"}],
            "artifacts": {
                **_notes_artifact(
                    [
                        {
                            "note_id": 54,
                            "title": "函数",
                            "kp_ids": [137],
                            "kp_names": ["单调性"],
                        }
                    ]
                ),
                "step_3": {
                    "tool": "make_mindmap",
                    "input": {},
                    "output": {
                        "mermaid": "mindmap\n  root((导图))",
                        "fallback_text": "- 导图",
                    },
                },
            },
        }
    )
    assert result["mermaid"].startswith("mindmap")
    assert "引用：笔记 #54" in result["summary_md"]
    assert result["citations"] == [{"note_id": 54, "note_title": "函数"}]

def test_weekly_mindmap_runs_through_engine_in_eight_steps():
    from app.ai.agents.engine import AgentEngine, RunContext
    from app.ai.agents.state import new_state

    fake = SimpleNamespace(
        chat=lambda *a, **k: SimpleNamespace(
            text=(
                '{"title":"过去 7 天学习导图","branches":[{"kp_id":137,'
                '"title":"单调性","conclusion":"复习了定义法与图像法。",'
                '"note_ids":[54],"children":["定义法"]}]}'
            ),
            total_tokens=50,
        )
    )
    spec = WeeklyMindmapTaskSpec({"days": 7}, now=NOW, llm_client=fake)
    steps: list[dict] = []

    class Recorder:
        def record(self, *, step_no, thought, status, state, **kwargs):  # noqa: ANN001
            steps.append({"step_no": step_no, "tool": kwargs.get("tool_name")})

    def invoker(name, ctx, payload):  # noqa: ANN001
        if name == "list_notes":
            return {
                "items": [
                    {
                        "note_id": 54,
                        "title": "函数",
                        "preview": "内容",
                        "kp_ids": [137],
                        "kp_names": ["单调性"],
                    }
                ]
            }
        if name == "get_kp_subgraph":
            return {"nodes": [{"kp_id": 137, "name": "单调性"}], "edges": []}
        from app.ai.agents.tools import invoke_tool

        return invoke_tool(name, ctx, payload).model_dump(mode="json")

    engine = AgentEngine(
        spec,
        RunContext(user=SimpleNamespace(id=18), recorder=Recorder(), tool_invoker=invoker),
    )
    final = engine.run(
        new_state(user_id=18, task_input={"days": 7}, token_budget=20000, max_steps=12)
    )
    assert final["status"] == "succeeded"
    assert final["result"]["mermaid"].startswith("mindmap")
    assert final["result"]["note_count"] == 1
    assert final["result"]["citations"] == [{"note_id": 54, "note_title": "函数"}]
    assert final["token_cost"] == 50
    assert len(steps) == 8


def test_weekly_accepts_token_budget_but_rejects_too_small():
    data = WeeklyMindmapTaskSpec.validate_input({"days": 7, "token_budget": 100})
    assert data["token_budget"] == 100
    with pytest.raises(InvalidParamError):
        WeeklyMindmapTaskSpec.validate_input({"days": 7, "token_budget": 99})


def test_weekly_validation_message_is_chinese():
    with pytest.raises(InvalidParamError) as exc:
        WeeklyMindmapTaskSpec.validate_input({"days": 0})
    assert "数值" in str(exc.value)
