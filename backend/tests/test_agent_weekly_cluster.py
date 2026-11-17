"""S6-3 聚类适配器：严格 JSON、引用校验、重试与 token。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.agents.tasks import weekly_mindmap as wm
from app.ai.agents.tasks.weekly_mindmap import ClusterContext, ClusterError

VALID = (
    '{"title":"上周学习导图","branches":['
    '{"kp_id":137,"title":"函数的单调性","conclusion":"复习了定义法与图像法。",'
    '"note_ids":[54],"children":["定义法","图像法"]}]}'
)


class FakeLLM:
    def __init__(self, texts):  # noqa: ANN001
        self.texts = list(texts)
        self.calls: list[SimpleNamespace] = []

    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):  # noqa: ANN001
        self.calls.append(
            SimpleNamespace(
                scene=scene, max_tokens=max_tokens, messages=messages, temperature=temperature
            )
        )
        return SimpleNamespace(text=self.texts.pop(0), total_tokens=120)


def _context() -> ClusterContext:
    return ClusterContext(
        days=7,
        notes=[
            {
                "note_id": 54,
                "title": "函数",
                "preview": "内容",
                "kp_names": ["函数的单调性"],
            }
        ],
        subgraphs=[
            {
                "nodes": [{"kp_id": 137, "name": "函数的单调性"}],
                "edges": [],
            }
        ],
    )


def test_cluster_prompt_contains_notes_and_schema():
    text = wm.render_cluster_prompt(_context())
    assert "note_id" in text and "函数的单调性" in text
    assert "branches" in text
    assert "54" in text


def test_generate_cluster_returns_result_and_tokens():
    llm = FakeLLM([VALID])
    result, tokens = wm.generate_cluster(_context(), llm_client=llm)
    assert result.title == "上周学习导图"
    assert result.branches[0].note_ids == [54]
    assert result.branches[0].kp_id == 137
    assert tokens == 120
    assert llm.calls[0].scene == "agent"
    assert llm.calls[0].max_tokens == 2200


def test_generate_cluster_retries_then_raises():
    llm = FakeLLM(["x", "y", "z"])
    with pytest.raises(ClusterError):
        wm.generate_cluster(_context(), llm_client=llm)


def test_generate_cluster_filters_invalid_citations_and_kp():
    bad = VALID.replace('"note_ids":[54]', '"note_ids":[999]').replace(
        '"kp_id":137', '"kp_id":999'
    )
    llm = FakeLLM([bad, bad, bad])
    with pytest.raises(ClusterError):
        wm.generate_cluster(_context(), llm_client=llm)


def test_generate_cluster_keeps_valid_part_of_citations():
    mixed = VALID.replace('"note_ids":[54]', '"note_ids":[54,999]').replace(
        '"kp_id":137', '"kp_id":999'
    )
    llm = FakeLLM([mixed])
    result, _ = wm.generate_cluster(_context(), llm_client=llm)
    assert result.branches[0].note_ids == [54]
    assert result.branches[0].kp_id is None