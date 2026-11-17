"""S6-1 get_kp_subgraph：BFS 跳数与已审核边过滤。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.agents.tools import get_kp_subgraph as tool
from app.ai.agents.tools.base import ToolContext
from app.core.exceptions import NotFoundError


class _Node:
    def __init__(self, kp_id: int, name: str, *, level: int = 3, parent_id: int | None = None):
        self.id = kp_id
        self.name = name
        self.level = level
        self.parent_id = parent_id
        self.exam_weight = 0.5
        self.mastery = 0.3 if kp_id == 1 else None


class _Edge:
    def __init__(self, src: int, dst: int, relation: str = "related"):
        self.src_kp_id = src
        self.dst_kp_id = dst
        self.relation = relation
        self.weight = 0.8


class _Session:
    def __init__(self, kp):
        self.kp = kp

    def get(self, model, pk):  # noqa: ANN001, ANN201
        return self.kp


def _ctx(kp) -> ToolContext:  # noqa: ANN001
    return ToolContext(session=_Session(kp), user=SimpleNamespace(id=50))  # type: ignore[arg-type]


def test_bfs_subgraph_respects_depth_and_is_undirected():
    edges = [(1, 2), (2, 3), (3, 4)]
    assert tool._bfs_subgraph([1, 2, 3, 4], edges, 2, 1) == {1, 2, 3}
    assert tool._bfs_subgraph([1, 2, 3, 4], edges, 2, 2) == {1, 2, 3, 4}


def test_get_kp_subgraph_returns_nodes_and_edges(monkeypatch):
    snapshot = SimpleNamespace(
        nodes=[_Node(1, "函数", level=2), _Node(2, "定义域"), _Node(3, "值域")],
        edges=[_Edge(1, 2, "contains"), _Edge(1, 3, "related")],
    )
    monkeypatch.setattr(
        tool.graph_service, "snapshot", lambda *args, **kwargs: snapshot
    )
    out = tool.get_kp_subgraph(
        _ctx(SimpleNamespace(id=1, subject_id=7)), tool.GetKpSubgraphIn(kp_id=1, depth=1)
    )
    assert out.center_kp_id == 1
    assert out.subject_id == 7
    assert [node.kp_id for node in out.nodes] == [1, 2, 3]
    assert [edge.relation for edge in out.edges] == ["contains", "related"]
    assert out.nodes[0].mastery == 0.3
    assert out.nodes[1].mastery is None


def test_get_kp_subgraph_missing_kp_raises_404():
    with pytest.raises(NotFoundError):
        tool.get_kp_subgraph(_ctx(None), tool.GetKpSubgraphIn(kp_id=999, depth=1))