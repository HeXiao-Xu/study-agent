"""S4-5 build 编排：四类关系、幂等墓碑、调用闸门、dry-run。

用 FakeSession 而非 SQLite：knowledge_points 带 pgvector 列，SQLite 建不了表；
这里要验证的是编排决策（哪些边该写、哪些该跳），不是 SQL 本身。
"""
from __future__ import annotations

import json

import pytest

from app.models.enums import EdgeReviewStatus
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.services import graph_service
from app.services.graph_service import BuildSummary


class FakeLLM:
    """按 Prompt 内容区分「前置推断」与「配对复核」，返回预设 JSON。"""

    def __init__(self, prereq_items: dict[str, list[dict]], pair_accept: bool = True) -> None:
        self.prereq_items = prereq_items
        self.pair_accept = pair_accept
        self.calls = 0

    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
        self.calls += 1
        text = messages[0].content
        if "待复核配对" in text:
            payload = {
                "items": [
                    {"pair_id": index, "accept": self.pair_accept, "reason": "复核"}
                    for index in range(1, 9)
                ]
            }
        else:
            name = text.split("名称：")[1].split("\n")[0].strip()
            payload = {"items": self.prereq_items.get(name, [])}

        class _Resp:
            pass

        response = _Resp()
        response.text = json.dumps(payload)
        return response


def _kp(
    kp_id: int, name: str, level: int, parent_id: int | None, vec: list[float]
) -> KnowledgePoint:
    return KnowledgePoint(
        id=kp_id,
        subject_id=7,
        name=name,
        code=f"c{kp_id}",
        level=level,
        parent_id=parent_id,
        embedding=vec,
        order_no=kp_id,
    )


class FakeSession:
    def __init__(
        self, nodes: list[KnowledgePoint], edges: list[KnowledgeEdge] | None = None
    ) -> None:
        self.nodes = nodes
        self.edges = edges or []
        self.added: list[KnowledgeEdge] = []
        self.flushes = 0

    def scalars(self, statement):
        text = str(statement)
        if "knowledge_edges" in text:
            return iter(self.edges)
        return iter(self.nodes)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flushes += 1


NODES = [
    _kp(1, "函数", 1, None, [1.0, 0.0]),
    _kp(2, "单调性", 2, 1, [0.99, 0.01]),
    _kp(3, "导数应用", 3, 2, [0.98, 0.02]),
    _kp(4, "极值", 3, 2, [0.10, 0.99]),
]


def test_build_creates_contains_edges_approved():
    session = FakeSession(NODES)
    summary = graph_service.build(
        session, subject_id=7, relations=["contains"], llm_client=FakeLLM({})
    )
    assert isinstance(summary, BuildSummary)
    assert summary.created == 3
    assert {edge.relation for edge in session.added} == {"contains"}
    assert all(
        edge.review_status == EdgeReviewStatus.APPROVED.value for edge in session.added
    )
    # ck_knowledge_edges_reviewed：非 pending 必须带 reviewed_at（真机验收抓到过漏填）
    assert all(edge.reviewed_at is not None for edge in session.added)


def test_build_creates_prerequisite_pending_edges():
    session = FakeSession(NODES)
    llm = FakeLLM({"导数应用": [{"src_kp_id": 1, "confidence": 0.85, "reason": "函数是前提"}]})
    summary = graph_service.build(
        session, subject_id=7, relations=["prerequisite"], llm_client=llm
    )
    assert summary.created == 1
    edge = session.added[0]
    assert (edge.src_kp_id, edge.dst_kp_id, edge.relation) == (1, 3, "prerequisite")
    assert edge.review_status == EdgeReviewStatus.PENDING.value
    assert float(edge.weight) == pytest.approx(0.85)
    assert edge.reviewed_at is None


def test_build_skips_approved_and_rejected_edges():
    approved = KnowledgeEdge(
        id=99,
        src_kp_id=1,
        dst_kp_id=2,
        relation="contains",
        source="ai",
        review_status=EdgeReviewStatus.APPROVED.value,
    )
    rejected = KnowledgeEdge(
        id=100,
        src_kp_id=1,
        dst_kp_id=3,
        relation="prerequisite",
        source="ai",
        review_status=EdgeReviewStatus.REJECTED.value,
    )
    session = FakeSession(NODES, [approved, rejected])
    llm = FakeLLM({"导数应用": [{"src_kp_id": 1, "confidence": 0.9, "reason": "重复"}]})
    summary = graph_service.build(
        session,
        subject_id=7,
        relations=["contains", "prerequisite"],
        llm_client=llm,
    )
    assert summary.skipped_approved >= 1
    assert summary.skipped_rejected == 1
    assert summary.created == 2  # 只剩另外两条 contains


def test_build_dry_run_writes_nothing():
    session = FakeSession(NODES)
    summary = graph_service.build(
        session,
        subject_id=7,
        relations=["contains"],
        llm_client=FakeLLM({}),
        dry_run=True,
    )
    assert summary.created == 3
    assert session.added == []


def test_build_refreshes_weight_on_pending_edge():
    pending = KnowledgeEdge(
        id=7,
        src_kp_id=1,
        dst_kp_id=3,
        relation="prerequisite",
        source="ai",
        weight=0.6,
        review_status=EdgeReviewStatus.PENDING.value,
    )
    session = FakeSession(NODES, [pending])
    llm = FakeLLM({"导数应用": [{"src_kp_id": 1, "confidence": 0.93, "reason": "更确定"}]})
    summary = graph_service.build(
        session, subject_id=7, relations=["prerequisite"], llm_client=llm
    )
    assert summary.updated == 1
    assert float(pending.weight) == pytest.approx(0.93)
    assert pending.review_status == EdgeReviewStatus.PENDING.value


def test_build_respects_max_calls_gate(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_service, "MAX_CALLS", 1)
    session = FakeSession(NODES)
    summary = graph_service.build(
        session, subject_id=7, relations=["prerequisite"], llm_client=FakeLLM({})
    )
    assert summary.truncated is True
    assert summary.calls == 1


def test_build_drops_reverse_prerequisite():
    existing = KnowledgeEdge(
        id=1,
        src_kp_id=3,
        dst_kp_id=2,
        relation="prerequisite",
        source="ai",
        review_status=EdgeReviewStatus.PENDING.value,
    )
    session = FakeSession(NODES, [existing])
    llm = FakeLLM({"单调性": [{"src_kp_id": 3, "confidence": 0.9, "reason": "反过来"}]})
    summary = graph_service.build(
        session, subject_id=7, relations=["prerequisite"], llm_client=llm
    )
    assert summary.created == 0


def test_build_rejects_unknown_relation():
    with pytest.raises(Exception):
        graph_service.build(
            FakeSession(NODES), subject_id=7, relations=["bogus"], llm_client=FakeLLM({})
        )


def test_build_creates_related_edges_from_pair_review():
    session = FakeSession(NODES)
    summary = graph_service.build(
        session, subject_id=7, relations=["related"], llm_client=FakeLLM({})
    )
    # NODES 里 2 与 3 余弦 ≈0.9999（同父且同向）→ 落在 confusable 桶，related 应为 0
    assert summary.created == 0
    assert all(edge.relation != "related" for edge in session.added)


def test_build_keeps_only_one_direction_within_a_run():
    """同一轮里 A→B 与 B→A 不能同时落库（真机验收抓到过 120/122 反向对）。"""
    session = FakeSession(NODES)
    llm = FakeLLM(
        {
            "单调性": [{"src_kp_id": 3, "confidence": 0.9, "reason": "反向"}],
            "导数应用": [{"src_kp_id": 2, "confidence": 0.9, "reason": "正向"}],
        }
    )
    summary = graph_service.build(
        session, subject_id=7, relations=["prerequisite"], llm_client=llm
    )
    pairs = {(edge.src_kp_id, edge.dst_kp_id) for edge in session.added}
    assert not (pairs & {(dst, src) for src, dst in pairs}), pairs
    assert summary.created == len(pairs)
