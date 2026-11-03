"""S4-5 LLM 适配器：严格 JSON、候选白名单、重试与异常。"""
from __future__ import annotations

import json

import pytest

from app.ai.graph.candidates import KpBrief, KpCandidate, Pair
from app.ai.graph.relation_builder import (
    GraphBuildError,
    infer_prerequisites,
    review_pairs,
)


class FakeLLM:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, object]] = []

    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
        self.calls.append({"messages": messages, "scene": scene, "max_tokens": max_tokens})
        text = self.replies.pop(0)

        class _Resp:
            pass

        response = _Resp()
        response.text = text
        return response


TARGET = KpBrief(kp_id=10, name="导数应用", level=3, parent_id=2, path="函数 / 导数 / 导数应用")
CANDS = [
    KpCandidate(kp_id=2, name="单调性", path="函数 / 单调性", cos=0.91),
    KpCandidate(kp_id=11, name="极值", path="函数 / 极值", cos=0.80),
]


def test_infer_prerequisites_parses_items_and_uses_graph_scene():
    client = FakeLLM(
        [json.dumps({"items": [{"src_kp_id": 2, "confidence": 0.9, "reason": "单调性定义"}]})]
    )
    out = infer_prerequisites(target=TARGET, candidates=CANDS, client=client)
    assert [item.src_kp_id for item in out] == [2]
    assert out[0].confidence == pytest.approx(0.9)
    assert client.calls[0]["scene"] == "graph"


def test_infer_prerequisites_drops_ids_outside_whitelist():
    client = FakeLLM(
        [json.dumps({"items": [{"src_kp_id": 999, "confidence": 0.99, "reason": "幻觉"}]})]
    )
    assert infer_prerequisites(target=TARGET, candidates=CANDS, client=client) == []


def test_infer_prerequisites_drops_low_confidence():
    client = FakeLLM(
        [json.dumps({"items": [{"src_kp_id": 2, "confidence": 0.2, "reason": "弱"}]})]
    )
    assert infer_prerequisites(target=TARGET, candidates=CANDS, client=client) == []


def test_infer_prerequisites_keeps_at_most_two_by_confidence():
    reply = json.dumps(
        {"items": [
            {"src_kp_id": 2, "confidence": 0.6, "reason": "a"},
            {"src_kp_id": 11, "confidence": 0.9, "reason": "b"},
            {"src_kp_id": 11, "confidence": 0.55, "reason": "c"},
        ]}
    )
    out = infer_prerequisites(target=TARGET, candidates=CANDS, client=FakeLLM([reply]))
    assert [item.src_kp_id for item in out] == [11, 2]


def test_infer_prerequisites_retries_then_raises():
    client = FakeLLM(["not json", "still not json", "{oops"])
    with pytest.raises(GraphBuildError):
        infer_prerequisites(target=TARGET, candidates=CANDS, client=client)
    assert len(client.calls) == 3


def test_infer_prerequisites_tolerates_unescaped_latex():
    reply = '{"items": [{"src_kp_id": 2, "confidence": 0.8, "reason": "把 \\sqrt{x} 讲清"}]}'
    out = infer_prerequisites(target=TARGET, candidates=CANDS, client=FakeLLM([reply]))
    assert out[0].src_kp_id == 2


def test_infer_prerequisites_short_circuits_without_candidates():
    client = FakeLLM([])
    assert infer_prerequisites(target=TARGET, candidates=[], client=client) == []
    assert client.calls == []


def test_review_pairs_returns_verdict_per_pair():
    pairs = [(1, Pair(2, 10, 0.95)), (2, Pair(3, 7, 0.88))]
    client = FakeLLM(
        [json.dumps({"items": [
            {"pair_id": 1, "accept": True, "reason": "条件不同"},
            {"pair_id": 2, "accept": False, "reason": "只是同模块"},
        ]})]
    )
    out = review_pairs(pairs=pairs, relation="confusable", client=client)
    assert {item.pair_id: item.accept for item in out} == {1: True, 2: False}
    assert client.calls[0]["scene"] == "graph"


def test_review_pairs_rejects_unknown_pair_id():
    """越界 pair_id 视为无效输出：重试两次仍无效则报错，不放行任何结论。"""
    pairs = [(1, Pair(2, 10, 0.95))]
    reply = json.dumps({"items": [{"pair_id": 7, "accept": True, "reason": "越界"}]})
    client = FakeLLM([reply, reply, reply])
    with pytest.raises(GraphBuildError):
        review_pairs(pairs=pairs, relation="related", client=client)


def test_review_pairs_retries_then_raises():
    pairs = [(1, Pair(2, 10, 0.95))]
    client = FakeLLM(["[]", "{}", "nope"])
    with pytest.raises(GraphBuildError):
        review_pairs(pairs=pairs, relation="related", client=client)
    assert len(client.calls) == 3