"""S6-1 make_mindmap：把节点/边转成 Mermaid 思维导图，失败时给纯文本结构。"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import Field

from app.ai.agents.tools.base import ToolContext, ToolInput, ToolOutput, ToolSpec

MAX_NODES = 80
MAX_LABEL = 40
_BRACKET_MAP = str.maketrans(
    {"(": "（", ")": "）", "[": "【", "]": "】", "{": "｛", "}": "｝", "<": "＜", ">": "＞"}
)


class MindmapNode(ToolInput):
    id: str | int
    name: str = Field(min_length=1, max_length=80)
    parent_id: str | int | None = None


class MindmapEdge(ToolInput):
    src: str | int
    dst: str | int
    relation: str | None = None


class MakeMindmapIn(ToolInput):
    title: str = Field(default="思维导图", min_length=1, max_length=100)
    nodes: list[MindmapNode] = Field(min_length=1, max_length=MAX_NODES)
    edges: list[MindmapEdge] = Field(default_factory=list, max_length=160)


class MindmapOut(ToolOutput):
    mermaid: str
    fallback_text: str
    node_count: int
    edge_count: int
    truncated: bool
    mode: Literal["mindmap", "graph"]


def _sanitize_label(text: str) -> tuple[str, bool]:
    clean = re.sub(r"\s+", " ", text).strip().translate(_BRACKET_MAP)
    if len(clean) > MAX_LABEL:
        return clean[:MAX_LABEL] + "…", True
    return clean, False


def _as_edge(edge: MindmapEdge | Mapping[str, Any]) -> MindmapEdge:
    return edge if isinstance(edge, MindmapEdge) else MindmapEdge.model_validate(edge)


def _dedupe_nodes(nodes: Sequence[MindmapNode]) -> tuple[list[MindmapNode], bool]:
    seen: set[str] = set()
    kept: list[MindmapNode] = []
    for node in nodes:
        node_id = str(node.id)
        if node_id in seen:
            continue
        seen.add(node_id)
        kept.append(node)
    truncated = len(kept) > MAX_NODES
    return kept[:MAX_NODES], truncated


def _parent_map(
    nodes: Sequence[MindmapNode], edges: Sequence[MindmapEdge], ids: set[str]
) -> tuple[dict[str, str], bool]:
    """返回 子→父；invalid 表示有环/多父/自环，需要降级成 graph。"""
    parent: dict[str, str] = {}
    invalid = False
    from_fields = any(node.parent_id is not None for node in nodes)
    if from_fields:
        for node in nodes:
            node_id = str(node.id)
            if node.parent_id is None:
                continue
            pid = str(node.parent_id)
            if pid == node_id:
                invalid = True
                continue
            if pid in ids:
                parent[node_id] = pid
        return parent, invalid

    # 没有 parent_id 时用边；优先 contains，保持输入顺序
    contains = [edge for edge in edges if (edge.relation or "") == "contains"]
    usable = contains or list(edges)
    for edge in usable:
        src, dst = str(edge.src), str(edge.dst)
        if src not in ids or dst not in ids or src == dst:
            invalid = True
            continue
        if dst in parent:
            invalid = True
            continue
        parent[dst] = src
    return parent, invalid


def _has_cycle(ids: Sequence[str], parent: Mapping[str, str]) -> bool:
    for start in ids:
        seen: set[str] = set()
        current = start
        while current in parent:
            if current in seen:
                return True
            seen.add(current)
            current = parent[current]
    return False


def _tree_lines(
    roots: Sequence[str],
    children: Mapping[str, list[str]],
    labels: Mapping[str, str],
    *,
    prefix: str,
    depth: int,
    bullet: str = "",
) -> list[str]:
    lines: list[str] = []
    for node_id in roots:
        lines.append(f"{prefix * depth}{bullet}{labels[node_id]}")
        lines.extend(
            _tree_lines(
                children.get(node_id, []),
                children,
                labels,
                prefix=prefix,
                depth=depth + 1,
                bullet=bullet,
            )
        )
    return lines


def build_mindmap(
    title: str,
    nodes: Sequence[MindmapNode],
    edges: Sequence[MindmapEdge | Mapping[str, Any]] = (),
) -> MindmapOut:
    kept, dropped = _dedupe_nodes(nodes)
    label_map: dict[str, str] = {}
    labels_truncated = False
    for node in kept:
        label, cut = _sanitize_label(node.name)
        label_map[str(node.id)] = label
        labels_truncated = labels_truncated or cut
    title_label, title_cut = _sanitize_label(title)
    labels_truncated = labels_truncated or title_cut

    normalized_edges = [_as_edge(edge) for edge in edges]
    ids = [str(node.id) for node in kept]
    id_set = set(ids)
    parent, invalid = _parent_map(kept, normalized_edges, id_set)
    if _has_cycle(ids, parent):
        invalid = True

    truncated = dropped or labels_truncated
    if invalid:
        mermaid, fallback = _graph_output(kept, normalized_edges, parent, label_map)
        mode: Literal["mindmap", "graph"] = "graph"
    else:
        mermaid, fallback = _mindmap_output(
            title_label, ids, parent, label_map
        )
        mode = "mindmap"
    return MindmapOut(
        mermaid=mermaid,
        fallback_text=fallback,
        node_count=len(kept),
        edge_count=len(normalized_edges),
        truncated=truncated,
        mode=mode,
    )


def _mindmap_output(
    title: str,
    ids: Sequence[str],
    parent: Mapping[str, str],
    labels: Mapping[str, str],
) -> tuple[str, str]:
    children: dict[str, list[str]] = {}
    roots: list[str] = []
    for node_id in ids:
        if node_id in parent:
            children.setdefault(parent[node_id], []).append(node_id)
        else:
            roots.append(node_id)
    lines = ["mindmap", f"  root(({title}))"]
    lines.extend(_tree_lines(roots, children, labels, prefix="  ", depth=2))
    fallback = [f"- {title}"]
    fallback.extend(
        _tree_lines(roots, children, labels, prefix="  ", depth=1, bullet="- ")
    )
    return "\n".join(lines), "\n".join(fallback)


def _graph_output(
    nodes: Sequence[MindmapNode],
    edges: Sequence[MindmapEdge],
    parent: Mapping[str, str],
    labels: Mapping[str, str],
) -> tuple[str, str]:
    index = {str(node.id): position for position, node in enumerate(nodes)}
    lines = ["graph TD"]
    lines.extend(f'  n{i}["{labels[str(node.id)]}"]' for i, node in enumerate(nodes))
    pairs: list[tuple[str, str]] = [(src, dst) for dst, src in parent.items()]
    pairs.extend((str(edge.src), str(edge.dst)) for edge in edges)
    seen: set[tuple[str, str]] = set()
    for src, dst in pairs:
        if src not in index or dst not in index or src == dst or (src, dst) in seen:
            continue
        seen.add((src, dst))
        lines.append(f"  n{index[src]} --> n{index[dst]}")
    fallback = [f"- {labels[str(node.id)]}" for node in nodes]
    fallback.extend(f"- {labels[src]} --> {labels[dst]}" for src, dst in sorted(seen))
    return "\n".join(lines), "\n".join(fallback)


def _handler(ctx: ToolContext, data: MakeMindmapIn) -> MindmapOut:
    return build_mindmap(data.title, data.nodes, data.edges)


SPEC = ToolSpec(
    name="make_mindmap",
    description=(
        "用途：把知识点节点与关系转成 Mermaid 思维导图文本，并附带纯文本结构降级。"
        "参数 title 是导图标题，nodes 至少 1 个（id/name/parent_id），edges 可选（src/dst/relation）。"
        "返回 mermaid（树合法时为 mindmap，否则为 graph TD）、fallback_text、node_count/edge_count 与 truncated。"
    ),
    input_model=MakeMindmapIn,
    output_model=MindmapOut,
    handler=_handler,
)