"""S4-6 图谱快照：只出 approved 边、pending 只计数、错题按用户、接口权限。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.exceptions import NotFoundError
from app.core.security import create_access_token
from app.main import app
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.models.subject import Subject
from app.models.user import User
from app.schemas.kp import GraphSnapshotOut
from app.services import graph_service

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


def _node(
    kp_id: int, name: str, *, level: int = 3, parent_id: int | None = 1
) -> KnowledgePoint:
    node = KnowledgePoint(
        subject_id=7,
        name=name,
        level=level,
        parent_id=parent_id,
        exam_weight=Decimal("0.800"),
    )
    node.id = kp_id
    return node


def _edge(edge_id: int, src: int, dst: int, relation: str, status: str) -> KnowledgeEdge:
    edge = KnowledgeEdge(
        src_kp_id=src,
        dst_kp_id=dst,
        relation=relation,
        source="ai",
        review_status=status,
        weight=Decimal("0.900"),
        reviewed_at=None if status == "pending" else NOW,
    )
    edge.id = edge_id
    return edge


class FakeSnapshotSession:
    """按 SQL 里的表名分派：scalars 分 nodes/edges，execute 只服务错题计数。"""

    def __init__(
        self,
        *,
        subject: Subject | None,
        nodes: list[KnowledgePoint],
        edges: list[KnowledgeEdge],
        mistake_rows: list[tuple[int, int]] | None = None,
        pending: int = 0,
    ) -> None:
        self.subject = subject
        self.nodes = nodes
        self.edges = edges
        self.mistake_rows = mistake_rows or []
        self.mastery_rows: list[tuple[int, object, object, datetime | None]] = []
        self.pending = pending
        self.committed = 0
        self.edge_sql = ""
        self.mastery_sql = ""

    def get(self, model, pk):  # noqa: ANN001, ANN201
        return self.subject if model is Subject else None

    def scalars(self, statement):  # noqa: ANN001, ANN201
        sql = str(statement)
        if "knowledge_edges" in sql:
            # 假会话不会真的执行 WHERE，这里把编译后的 SQL 留出来断言过滤条件，
            # 返回集只放 approved（模拟数据库的结果）
            self.edge_sql = str(
                statement.compile(compile_kwargs={"literal_binds": True})
            )
            return iter(self.edges)
        return iter(self.nodes)

    def execute(self, statement):  # noqa: ANN001, ANN201
        sql = str(statement)
        if "mastery" in sql:
            self.mastery_sql = str(
                statement.compile(compile_kwargs={"literal_binds": True})
            )
            rows = self.mastery_rows
        else:
            rows = self.mistake_rows

        class _Rows:
            def all(self):
                return rows

        return _Rows()

    def scalar(self, statement):  # noqa: ANN001, ANN201
        return self.pending

    def commit(self) -> None:
        self.committed += 1


def _session(**kwargs) -> FakeSnapshotSession:  # noqa: ANN003
    subject = kwargs.pop("subject", Subject(name="高中数学", code="math"))
    subject.id = 7
    kwargs.setdefault("edges", [])
    kwargs.setdefault(
        "nodes", [_node(1, "函数", level=1, parent_id=None), _node(2, "导数")]
    )
    return FakeSnapshotSession(subject=subject, **kwargs)


def test_snapshot_keeps_only_approved_edges() -> None:
    session = _session(edges=[_edge(1, 1, 2, "prerequisite", "approved")])
    out = graph_service.snapshot(session, subject_id=7, user_id=50)
    assert [(e.relation, e.src_kp_id, e.dst_kp_id) for e in out.edges] == [
        ("prerequisite", 1, 2)
    ]
    assert out.stats.edges == 1
    # 假会话不执行 WHERE，靠编译后的 SQL 证明 pending/rejected 不会进快照
    assert "knowledge_edges.review_status = 'approved'" in session.edge_sql


def test_snapshot_counts_pending_separately() -> None:
    session = _session(edges=[_edge(1, 1, 2, "prerequisite", "approved")], pending=50)
    out = graph_service.snapshot(session, subject_id=7, user_id=50)
    assert out.stats.pending_edges == 50


def test_snapshot_by_relation_always_has_four_keys() -> None:
    session = _session(edges=[_edge(1, 1, 2, "prerequisite", "approved")])
    out = graph_service.snapshot(session, subject_id=7, user_id=50)
    assert out.stats.by_relation == {
        "contains": 0,
        "prerequisite": 1,
        "related": 0,
        "confusable": 0,
    }


def test_snapshot_fills_mistake_count_by_kp() -> None:
    session = _session(mistake_rows=[(2, 3)])
    out = graph_service.snapshot(session, subject_id=7, user_id=50)
    counts = {node.id: node.mistake_count for node in out.nodes}
    assert counts == {1: 0, 2: 3}


def test_snapshot_attaches_decayed_mastery() -> None:
    session = _session()
    session.mastery_rows = [
        (2, Decimal("0.800"), Decimal("10.00"), NOW - timedelta(days=10))
    ]
    out = graph_service.snapshot(session, subject_id=7, user_id=50, now=NOW)
    by_id = {node.id: node for node in out.nodes}
    assert by_id[2].mastery == pytest.approx(0.294)  # 0.8·exp(−10/10)
    assert by_id[1].mastery is None  # 没有行 = 未评估


def test_snapshot_ignores_other_users_mastery() -> None:
    session = _session()
    session.mastery_rows = []
    out = graph_service.snapshot(session, subject_id=7, user_id=50, now=NOW)
    assert all(node.mastery is None for node in out.nodes)
    assert "mastery.user_id = 50" in session.mastery_sql
    assert "mastery.kp_id IN (1, 2)" in session.mastery_sql


def test_snapshot_unknown_subject_raises_not_found() -> None:
    session = FakeSnapshotSession(subject=None, nodes=[], edges=[])
    with pytest.raises(NotFoundError):
        graph_service.snapshot(session, subject_id=99, user_id=50)


def test_snapshot_does_not_commit() -> None:
    session = _session()
    graph_service.snapshot(session, subject_id=7, user_id=50)
    assert session.committed == 0


class FakeSession:
    """接口层的假会话：get_current_user 只查 User。"""

    def __init__(self, user: User) -> None:
        self.user = user

    def get(self, model, pk):  # noqa: ANN001, ANN201
        return self.user if model is User else None

    def scalar(self, statement):  # noqa: ANN001, ANN201
        return self.user if "users" in str(statement) else 0

    def flush(self) -> None:
        return None


def _user(role: str) -> User:
    user = User(
        username=f"{role}_s46", nickname=role, grade="高二", role=role, password_hash="x"
    )
    user.id = 50 if role == "student" else 9
    return user


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


def _snapshot_out() -> GraphSnapshotOut:
    from app.schemas.kp import (
        GraphSnapshotEdge,
        GraphSnapshotNode,
        GraphSnapshotStats,
        GraphSubjectBrief,
    )

    return GraphSnapshotOut(
        subject=GraphSubjectBrief(id=7, name="高中数学"),
        nodes=[
            GraphSnapshotNode(
                id=2, name="导数", level=3, parent_id=1, exam_weight=0.8, mistake_count=1
            )
        ],
        edges=[
            GraphSnapshotEdge(
                src_kp_id=1, dst_kp_id=2, relation="prerequisite", weight=0.9
            )
        ],
        stats=GraphSnapshotStats(
            nodes=2,
            edges=1,
            pending_edges=50,
            by_relation={"contains": 0, "prerequisite": 1, "related": 0, "confusable": 0},
        ),
    )


def test_snapshot_api_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/kp/graph/snapshot").status_code == 401


def test_snapshot_api_allows_student(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    student = _user("student")
    app.dependency_overrides[get_db] = lambda: FakeSession(student)
    monkeypatch.setattr(graph_service, "snapshot", lambda session, **kw: _snapshot_out())
    resp = client.get("/api/v1/kp/graph/snapshot?subject_id=7", headers=_headers(student))
    assert resp.status_code == 200
    assert resp.json()["data"]["stats"]["pending_edges"] == 50