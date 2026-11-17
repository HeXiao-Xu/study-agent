"""S6-1 get_kp_subgraph：知识点及其 N 跳前置/相关/包含关系（只取已审核边）。"""
from __future__ import annotations

from collections import deque
from collections.abc import Sequence

from pydantic import Field

from app.ai.agents.tools.base import ToolContext, ToolInput, ToolOutput, ToolSpec
from app.core.exceptions import NotFoundError
from app.models.knowledge_point import KnowledgePoint
from app.services import graph_service

MAX_DEPTH = 3


class GetKpSubgraphIn(ToolInput):
    kp_id: int = Field(ge=1)
    depth: int = Field(default=1, ge=1, le=MAX_DEPTH)


class KpSubgraphNode(ToolOutput):
    kp_id: int
    name: str
    level: int
    parent_id: int | None = None
    exam_weight: float | None = None
    mastery: float | None = None


class KpSubgraphEdge(ToolOutput):
    src_kp_id: int
    dst_kp_id: int
    relation: str
    weight: float | None = None


class KpSubgraphOut(ToolOutput):
    center_kp_id: int
    subject_id: int
    node_count: int
    edge_count: int
    nodes: list[KpSubgraphNode]
    edges: list[KpSubgraphEdge]


def _bfs_subgraph(
    node_ids: Sequence[int],
    edges: Sequence[tuple[int, int]],
    center: int,
    depth: int,
) -> set[int]:
    """把已审核边视为无向，返回距中心 ≤ depth 的节点集合（含中心）。"""
    adjacency: dict[int, set[int]] = {int(node_id): set() for node_id in node_ids}
    for src, dst in edges:
        src, dst = int(src), int(dst)
        if src not in adjacency or dst not in adjacency:
            continue
        adjacency[src].add(dst)
        adjacency[dst].add(src)
    seen = {center}
    queue: deque[tuple[int, int]] = deque([(center, 0)])
    while queue:
        current, distance = queue.popleft()
        if distance >= depth:
            continue
        for neighbor in adjacency.get(current, set()):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append((neighbor, distance + 1))
    return seen


def get_kp_subgraph(ctx: ToolContext, data: GetKpSubgraphIn) -> KpSubgraphOut:
    kp = ctx.session.get(KnowledgePoint, data.kp_id)
    if kp is None:
        raise NotFoundError("知识点不存在")
    snapshot = graph_service.snapshot(
        ctx.session,
        subject_id=kp.subject_id,
        user_id=ctx.user.id,
        now=ctx.now,
    )
    pairs = [(edge.src_kp_id, edge.dst_kp_id) for edge in snapshot.edges]
    kept = _bfs_subgraph(
        [node.id for node in snapshot.nodes], pairs, data.kp_id, data.depth
    )
    nodes = sorted(
        (node for node in snapshot.nodes if node.id in kept),
        key=lambda node: node.id,
    )
    edges = sorted(
        (
            edge
            for edge in snapshot.edges
            if edge.src_kp_id in kept and edge.dst_kp_id in kept
        ),
        key=lambda edge: (edge.src_kp_id, edge.dst_kp_id),
    )
    return KpSubgraphOut(
        center_kp_id=data.kp_id,
        subject_id=kp.subject_id,
        node_count=len(nodes),
        edge_count=len(edges),
        nodes=[
            KpSubgraphNode(
                kp_id=node.id,
                name=node.name,
                level=node.level,
                parent_id=node.parent_id,
                exam_weight=node.exam_weight,
                mastery=node.mastery,
            )
            for node in nodes
        ],
        edges=[
            KpSubgraphEdge(
                src_kp_id=edge.src_kp_id,
                dst_kp_id=edge.dst_kp_id,
                relation=edge.relation,
                weight=edge.weight,
            )
            for edge in edges
        ],
    )


SPEC = ToolSpec(
    name="get_kp_subgraph",
    description=(
        "用途：取一个知识点及其 N 跳前置/相关/包含关系，用于聚类、导图或薄弱点分析；"
        "只返回已审核的图谱边。"
        "参数 kp_id 是中心知识点，depth 取 1–3（默认 1）。"
        "返回中心点、学科、节点（含本人掌握度，未评估为 null）与边（src/dst/relation/weight）。"
    ),
    input_model=GetKpSubgraphIn,
    output_model=KpSubgraphOut,
    handler=get_kp_subgraph,
)