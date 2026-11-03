"""S4-5 审核与统计：幂等、批量跳过、非法状态。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.exceptions import InvalidParamError, NotFoundError
from app.models.enums import EdgeReviewStatus
from app.models.knowledge_edge import KnowledgeEdge
from app.models.user import User
from app.services import graph_service

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


class FakeSession:
    def __init__(self, edges: list[KnowledgeEdge]) -> None:
        self.edges = {edge.id: edge for edge in edges}
        self.flushed = 0

    def get(self, model, pk):
        return self.edges.get(pk)

    def flush(self):
        self.flushed += 1


def _edge(edge_id: int, *, status: str = "pending") -> KnowledgeEdge:
    return KnowledgeEdge(
        id=edge_id,
        src_kp_id=1,
        dst_kp_id=2,
        relation="prerequisite",
        source="ai",
        weight=0.8,
        review_status=status,
        reviewed_at=NOW if status != "pending" else None,
    )


REVIEWER = User(id=9, username="teacher_1", nickname="老师", grade="高二", role="teacher")


def test_review_edge_approve_sets_reviewer_and_time():
    session = FakeSession([_edge(1)])
    edge = graph_service.review_edge(session, edge_id=1, approve=True, reviewer=REVIEWER)
    assert edge.review_status == EdgeReviewStatus.APPROVED.value
    assert edge.reviewed_by == 9
    assert edge.reviewed_at is not None
    assert session.flushed == 1


def test_review_edge_is_idempotent():
    session = FakeSession([_edge(2)])
    first = graph_service.review_edge(session, edge_id=2, approve=False, reviewer=REVIEWER)
    stamp = first.reviewed_at
    second = graph_service.review_edge(session, edge_id=2, approve=False, reviewer=REVIEWER)
    assert second.review_status == EdgeReviewStatus.REJECTED.value
    assert second.reviewed_at >= stamp


def test_review_edge_can_flip_decision():
    session = FakeSession([_edge(3, status="approved")])
    edge = graph_service.review_edge(session, edge_id=3, approve=False, reviewer=REVIEWER)
    assert edge.review_status == EdgeReviewStatus.REJECTED.value


def test_review_edge_missing_raises_not_found():
    with pytest.raises(NotFoundError):
        graph_service.review_edge(
            FakeSession([]), edge_id=404, approve=True, reviewer=REVIEWER
        )


def test_review_edges_counts_updated_and_skipped():
    session = FakeSession([_edge(1), _edge(2)])
    updated, skipped = graph_service.review_edges(
        session, edge_ids=[1, 2, 999], approve=True, reviewer=REVIEWER
    )
    assert (updated, skipped) == (2, 1)


def test_review_edges_dedupes_repeated_ids():
    session = FakeSession([_edge(1)])
    updated, skipped = graph_service.review_edges(
        session, edge_ids=[1, 1, 1], approve=True, reviewer=REVIEWER
    )
    assert (updated, skipped) == (1, 0)


def test_review_edges_rejects_empty_list():
    with pytest.raises(InvalidParamError):
        graph_service.review_edges(
            FakeSession([]), edge_ids=[], approve=True, reviewer=REVIEWER
        )