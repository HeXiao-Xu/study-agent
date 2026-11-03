"""S4-5 图谱候选构造：全部纯函数，便于穷举边界。

设计取舍：
- 候选只看 top_k 近邻而非全量两两比较（108 节点尚可，但真到千级会拖死）；
- related 与 confusable 必须靠阈值分档，否则同一对会被两个 Prompt 各判一次、语义重叠；
- 无向关系统一按 (小 id, 大 id) 存一次，避免正反两条重复边。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import AbstractSet

from app.ai.align.scoring import cosine

RELATED_LO = 0.75
RELATED_HI = 0.90
CONFUSABLE_LO = 0.90
SAME_PARENT_LO = 0.75
TOPK = 8
PATH_GUARD = 10


@dataclass(frozen=True, slots=True)
class KpBrief:
    kp_id: int
    name: str
    level: int
    parent_id: int | None
    embedding: list[float] | None = None
    path: str = ""


@dataclass(frozen=True, slots=True)
class KpCandidate:
    kp_id: int
    name: str
    path: str
    cos: float


@dataclass(frozen=True, slots=True)
class Pair:
    src_kp_id: int
    dst_kp_id: int
    cos: float


def build_paths(nodes: Sequence[KpBrief]) -> dict[int, str]:
    """id → "祖先 / 祖先 / 自身"；脏数据成环时靠 PATH_GUARD 截断。"""
    by_id = {node.kp_id: node for node in nodes}
    paths: dict[int, str] = {}
    for node in nodes:
        names: list[str] = []
        cursor: KpBrief | None = node
        guard = 0
        while cursor is not None and guard < PATH_GUARD:
            names.append(cursor.name)
            cursor = (
                by_id.get(cursor.parent_id) if cursor.parent_id is not None else None
            )
            guard += 1
        paths[node.kp_id] = " / ".join(reversed(names))
    return paths


def prereq_candidates(
    target: KpBrief,
    nodes: Sequence[KpBrief],
    paths: Mapping[int, str],
    *,
    top_k: int = TOPK,
    exclude_ids: AbstractSet[int] = frozenset(),
) -> list[KpCandidate]:
    """候选前置：同 subject 内按余弦取 top_k，排除自身/父子/调用方指定集合。"""
    if not target.embedding:
        return []
    scored: list[KpCandidate] = []
    for node in nodes:
        if node.kp_id == target.kp_id or node.kp_id in exclude_ids:
            continue
        if not node.embedding:
            continue
        scored.append(
            KpCandidate(
                kp_id=node.kp_id,
                name=node.name,
                path=paths.get(node.kp_id, node.name),
                cos=cosine(target.embedding, node.embedding),
            )
        )
    scored.sort(key=lambda item: (-item.cos, item.kp_id))
    return scored[:top_k]


def pair_candidates(
    nodes: Sequence[KpBrief],
    *,
    related_lo: float = RELATED_LO,
    related_hi: float = RELATED_HI,
    confusable_lo: float = CONFUSABLE_LO,
    same_parent_lo: float = SAME_PARENT_LO,
    top_k: int = TOPK,
) -> tuple[list[Pair], list[Pair]]:
    """返回 (related, confusable)；同一对只进一个桶，confusable 优先。"""
    by_id = {node.kp_id: node for node in nodes}
    related: list[Pair] = []
    confusable: list[Pair] = []
    seen: set[tuple[int, int]] = set()
    for node in nodes:
        if not node.embedding:
            continue
        neighbors: list[Pair] = []
        for other in nodes:
            if other.kp_id == node.kp_id or not other.embedding:
                continue
            src, dst = sorted((node.kp_id, other.kp_id))
            neighbors.append(
                Pair(
                    src_kp_id=src,
                    dst_kp_id=dst,
                    cos=cosine(node.embedding, other.embedding),
                )
            )
        neighbors.sort(key=lambda item: (-item.cos, item.src_kp_id, item.dst_kp_id))
        for pair in neighbors[:top_k]:
            key = (pair.src_kp_id, pair.dst_kp_id)
            if key in seen:
                continue
            other = by_id[pair.dst_kp_id if pair.src_kp_id == node.kp_id else pair.src_kp_id]
            same_parent = (
                node.parent_id is not None and node.parent_id == other.parent_id
            )
            if pair.cos >= confusable_lo or (same_parent and pair.cos >= same_parent_lo):
                confusable.append(pair)
                seen.add(key)
            elif related_lo <= pair.cos < related_hi and not same_parent:
                related.append(pair)
                seen.add(key)
    related.sort(key=lambda item: (-item.cos, item.src_kp_id, item.dst_kp_id))
    confusable.sort(key=lambda item: (-item.cos, item.src_kp_id, item.dst_kp_id))
    return related, confusable


def direction_conflicts(existing: Sequence[tuple[int, int, str]]) -> set[tuple[int, int]]:
    """现存 prerequisite 有向对；插入 (a,b) 前若 (b,a) 在此集合中即为反向冲突。"""
    return {(src, dst) for src, dst, relation in existing if relation == "prerequisite"}