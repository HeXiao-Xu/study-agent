"""S4-6 节点详情：面包屑、四类邻居只取 approved、笔记/错题按本人过滤。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.exceptions import NotFoundError
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.services import graph_service

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


def _node(kp_id: int, name: str, *, level: int, parent_id: int | None) -> KnowledgePoint:
    node = KnowledgePoint(
        subject_id=7,
        name=name,
        level=level,
        parent_id=parent_id,
        description=None,
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


class FakeDetailSession:
    """get() 服务节点与祖先；scalars 服务邻居边；execute 分派名称/笔记/错题。"""

    def __init__(self, *, nodes, edges, notes=(), mistakes=()) -> None:
        self.nodes = {node.id: node for node in nodes}
        self.edges = edges
        self.notes = list(notes)
        self.mistakes = list(mistakes)
        self.edge_sql = ""
        self.committed = 0

    def get(self, model, pk):  # noqa: ANN001, ANN201
        return self.nodes.get(pk) if model is KnowledgePoint else None

    def scalars(self, statement):  # noqa: ANN001, ANN201
        # 假会话不执行 WHERE：SQL 留出来断言过滤条件，返回集模拟数据库的过滤结果
        self.edge_sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        return iter(
            [
                edge
                for edge in self.edges
                if edge.review_status == "approved" and edge.relation != "contains"
            ]
        )

    def execute(self, statement):  # noqa: ANN001, ANN201
        sql = str(statement)
        if "note_kps" in sql:
            rows = self.notes
        elif "mistakes" in sql:
            rows = self.mistakes
        else:
            rows = [(node.id, node.name) for node in self.nodes.values()]

        class _Rows:
            def all(self):
                return rows

        return _Rows()

    def commit(self) -> None:
        self.committed += 1


def _triangle():
    root = _node(1, "高中数学", level=1, parent_id=None)
    chapter = _node(2, "导数及其应用", level=2, parent_id=1)
    target = _node(3, "导数与函数的单调性", level=3, parent_id=2)
    other = _node(4, "函数的单调性", level=3, parent_id=1)
    successor = _node(5, "函数的极值与最值", level=3, parent_id=2)
    return [root, chapter, target, other, successor]


def test_node_detail_builds_path_from_root() -> None:
    nodes = _triangle()
    session = FakeDetailSession(nodes=nodes, edges=[])
    out = graph_service.node_detail(session, kp_id=3, user_id=50)
    assert out.path == ["高中数学", "导数及其应用", "导数与函数的单调性"]
    assert out.description is None
    assert out.prerequisites == [] and out.notes == [] and out.mistakes == []


def test_node_detail_splits_prerequisites_and_successors() -> None:
    nodes = _triangle()
    session = FakeDetailSession(
        nodes=nodes,
        edges=[
            _edge(1, 4, 3, "prerequisite", "approved"),
            _edge(2, 3, 5, "prerequisite", "approved"),
        ],
    )
    out = graph_service.node_detail(session, kp_id=3, user_id=50)
    assert [n.kp_id for n in out.prerequisites] == [4]
    assert [n.name for n in out.prerequisites] == ["函数的单调性"]
    assert [n.kp_id for n in out.successors] == [5]
    # 邻居查询本身就必须带 approved 与「排除 contains」两个条件
    assert "knowledge_edges.review_status = 'approved'" in session.edge_sql
    assert "knowledge_edges.relation != 'contains'" in session.edge_sql


def test_node_detail_ignores_non_approved_edges() -> None:
    nodes = _triangle()
    session = FakeDetailSession(
        nodes=nodes, edges=[_edge(1, 4, 3, "prerequisite", "pending")]
    )
    out = graph_service.node_detail(session, kp_id=3, user_id=50)
    assert out.prerequisites == []


def test_node_detail_ignores_contains_edges() -> None:
    nodes = _triangle()
    session = FakeDetailSession(
        nodes=nodes, edges=[_edge(1, 2, 3, "contains", "approved")]
    )
    out = graph_service.node_detail(session, kp_id=3, user_id=50)
    assert out.prerequisites == [] and out.successors == [] and out.related == []


def test_node_detail_returns_notes_and_mistakes_rows() -> None:
    nodes = _triangle()
    session = FakeDetailSession(
        nodes=nodes,
        edges=[],
        notes=[(7, "导数单调性整理", NOW)],
        mistakes=[(9, 33, "待订正", NOW, "已知函数 f(x)=…")],
    )
    out = graph_service.node_detail(session, kp_id=3, user_id=50)
    assert [(n.id, n.title) for n in out.notes] == [(7, "导数单调性整理")]
    assert [(m.id, m.question_id, m.stem) for m in out.mistakes] == [
        (9, 33, "已知函数 f(x)=…")
    ]
    assert out.mistake_count == 1


def test_node_detail_unknown_kp_raises_not_found() -> None:
    session = FakeDetailSession(nodes=_triangle(), edges=[])
    with pytest.raises(NotFoundError):
        graph_service.node_detail(session, kp_id=999, user_id=50)


def test_node_detail_does_not_commit() -> None:
    session = FakeDetailSession(nodes=_triangle(), edges=[])
    graph_service.node_detail(session, kp_id=3, user_id=50)
    assert session.committed == 0


def test_node_detail_api_requires_auth() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        assert client.get("/api/v1/kp/graph/nodes/3").status_code == 401


def test_node_detail_api_forwards_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.core.security import create_access_token
    from app.main import app
    from app.models.user import User
    from app.schemas.kp import GraphNodeDetailOut

    user = User(
        username="student_s46",
        nickname="s",
        grade="高二",
        role="student",
        password_hash="x",
    )
    user.id = 50

    class _Session:
        def get(self, model, pk):  # noqa: ANN001, ANN201
            return user if model is User else None

        def scalar(self, statement):  # noqa: ANN001, ANN201
            return user if "users" in str(statement) else 0

        def flush(self) -> None:
            return None

    captured: dict[str, int] = {}

    def fake_detail(session, *, kp_id: int, user_id: int):  # noqa: ANN001, ANN202
        captured["kp_id"] = kp_id
        captured["user_id"] = user_id
        return GraphNodeDetailOut(
            id=kp_id,
            name="导数",
            level=3,
            parent_id=2,
            subject_id=7,
            path=["高中数学"],
            mistake_count=0,
        )

    monkeypatch.setattr(graph_service, "node_detail", fake_detail)
    app.dependency_overrides[get_db] = lambda: _Session()
    token = create_access_token(user_id=50, role="student").token
    with TestClient(app) as client:
        resp = client.get(
            "/api/v1/kp/graph/nodes/3", headers={"Authorization": f"Bearer {token}"}
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert captured == {"kp_id": 3, "user_id": 50}
    assert resp.json()["data"]["path"] == ["高中数学"]