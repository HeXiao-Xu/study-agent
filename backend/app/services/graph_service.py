"""S4-5 知识图谱服务：构建、幂等墓碑、查询、人工审核（唯一入口）。

三段职责分得很开：
- 候选与分档在 `ai/graph/candidates.py`（纯函数，可穷举）；
- LLM 判定在 `ai/graph/relation_builder.py`（只吐结构化结论）；
- 这里只做编排与落库，并守住两条产品口径：
  AI 边默认 `pending`（等人工通过），`rejected` 当墓碑（重跑不复活）。
"""
from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.ai.graph import relation_builder
from app.ai.graph.candidates import (
    KpBrief,
    build_paths,
    direction_conflicts,
    pair_candidates,
    prereq_candidates,
)
from app.ai.llm import LLMClient
from app.core.exceptions import InvalidParamError
from app.models.enums import EdgeRelation, EdgeReviewStatus, EdgeSource
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.models.user import User

logger = logging.getLogger(__name__)

RELATIONS: tuple[str, ...] = (
    EdgeRelation.CONTAINS.value,
    EdgeRelation.PREREQUISITE.value,
    EdgeRelation.RELATED.value,
    EdgeRelation.CONFUSABLE.value,
)
MAX_CALLS = 180
PAIR_BATCH = 8
TASK_BUILD_GRAPH = "graph.build"
VALID_STATUSES = frozenset({"pending", "approved", "rejected", "all"})
SORTABLE = {
    "created_at": KnowledgeEdge.created_at,
    "weight": KnowledgeEdge.weight,
    "id": KnowledgeEdge.id,
}


@dataclass(slots=True)
class BuildSummary:
    subject_id: int
    nodes: int
    created: int
    updated: int
    skipped_approved: int
    skipped_rejected: int
    calls: int
    truncated: bool
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class _EdgePlan:
    src_kp_id: int
    dst_kp_id: int
    relation: str
    weight: float | None
    review_status: str


@dataclass(slots=True)
class _MergeStats:
    created: int = 0
    updated: int = 0
    skipped_approved: int = 0
    skipped_rejected: int = 0


class _CallBudget:
    """LLM 调用闸门：一次构建最多 MAX_CALLS 次，超了停手并标 truncated。"""

    def __init__(self, limit: int | None = None) -> None:
        self.limit = MAX_CALLS if limit is None else limit
        self.used = 0

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit

    def spend(self) -> None:
        self.used += 1


def _load_nodes(session: Session, subject_id: int) -> list[KnowledgePoint]:
    return list(
        session.scalars(
            select(KnowledgePoint)
            .where(KnowledgePoint.subject_id == subject_id)
            .order_by(KnowledgePoint.id)
        )
    )


def _load_edges(session: Session, node_ids: Sequence[int]) -> list[KnowledgeEdge]:
    if not node_ids:
        return []
    return list(
        session.scalars(
            select(KnowledgeEdge).where(KnowledgeEdge.src_kp_id.in_(list(node_ids)))
        )
    )


def _contains_plans(nodes: Sequence[KnowledgePoint]) -> list[_EdgePlan]:
    return [
        _EdgePlan(
            src_kp_id=node.parent_id,
            dst_kp_id=node.id,
            relation=EdgeRelation.CONTAINS.value,
            weight=None,
            review_status=EdgeReviewStatus.APPROVED.value,
        )
        for node in nodes
        if node.parent_id is not None
    ]


def _merge(session: Session, plans: Sequence[_EdgePlan], *, dry_run: bool) -> _MergeStats:
    stats = _MergeStats()
    existing = {
        (edge.src_kp_id, edge.dst_kp_id, edge.relation): edge
        for edge in session.scalars(select(KnowledgeEdge))
    }
    for plan in plans:
        found = existing.get((plan.src_kp_id, plan.dst_kp_id, plan.relation))
        if found is None:
            stats.created += 1
            if not dry_run:
                session.add(
                    KnowledgeEdge(
                        src_kp_id=plan.src_kp_id,
                        dst_kp_id=plan.dst_kp_id,
                        relation=plan.relation,
                        weight=plan.weight,
                        source=EdgeSource.AI.value,
                        review_status=plan.review_status,
                        # ck_knowledge_edges_reviewed 要求非 pending 必须有 reviewed_at；
                        # contains 是系统自动通过的，reviewed_by 留空
                        reviewed_at=None
                        if plan.review_status == EdgeReviewStatus.PENDING.value
                        else datetime.now(timezone.utc),
                    )
                )
            continue
        if found.review_status == EdgeReviewStatus.APPROVED.value:
            stats.skipped_approved += 1
            continue
        if found.review_status == EdgeReviewStatus.REJECTED.value:
            stats.skipped_rejected += 1
            logger.info(
                "graph_skip_rejected",
                extra={"edge_id": found.id, "relation": plan.relation},
            )
            continue
        stats.updated += 1
        if not dry_run and plan.weight is not None:
            found.weight = plan.weight
    if not dry_run:
        session.flush()
    return stats


def _brief(node: KnowledgePoint, path: str) -> KpBrief:
    return KpBrief(
        kp_id=node.id,
        name=node.name,
        level=node.level,
        parent_id=node.parent_id,
        embedding=list(node.embedding) if node.embedding is not None else None,
        path=path,
    )


def _prereq_plans(
    nodes: Sequence[KnowledgePoint],
    briefs: dict[int, KpBrief],
    paths: dict[int, str],
    *,
    limit: int | None,
    budget: _CallBudget,
    llm_client: LLMClient | None,
    known_pairs: set[tuple[int, int]],
) -> list[_EdgePlan]:
    targets = [node for node in nodes if node.level >= 2 and node.embedding is not None]
    if limit is not None:
        targets = targets[:limit]
    children_of: dict[int, set[int]] = {}
    for node in nodes:
        if node.parent_id is not None:
            children_of.setdefault(node.parent_id, set()).add(node.id)
    plans: list[_EdgePlan] = []
    for node in targets:
        if budget.exhausted:
            break
        exclude = {node.id} | children_of.get(node.id, set())
        if node.parent_id is not None:
            exclude.add(node.parent_id)
        candidates = prereq_candidates(
            briefs[node.id], list(briefs.values()), paths, exclude_ids=exclude
        )
        if not candidates:
            continue
        inferred = relation_builder.infer_prerequisites(
            target=briefs[node.id], candidates=candidates, client=llm_client
        )
        budget.spend()
        for item in inferred:
            if (node.id, item.src_kp_id) in known_pairs:
                logger.info(
                    "graph_direction_conflict",
                    extra={"src": item.src_kp_id, "dst": node.id},
                )
                continue
            plans.append(
                _EdgePlan(
                    src_kp_id=item.src_kp_id,
                    dst_kp_id=node.id,
                    relation=EdgeRelation.PREREQUISITE.value,
                    weight=round(item.confidence, 4),
                    review_status=EdgeReviewStatus.PENDING.value,
                )
            )
    return plans


def _pair_plans(
    briefs: dict[int, KpBrief],
    wanted: Sequence[str],
    *,
    budget: _CallBudget,
    llm_client: LLMClient | None,
) -> list[_EdgePlan]:
    related, confusable = pair_candidates(list(briefs.values()))
    buckets = {
        EdgeRelation.RELATED.value: related,
        EdgeRelation.CONFUSABLE.value: confusable,
    }
    plans: list[_EdgePlan] = []
    for relation in wanted:
        bucket = buckets.get(relation)
        if bucket is None:
            continue
        for start in range(0, len(bucket), PAIR_BATCH):
            if budget.exhausted:
                return plans
            batch = bucket[start : start + PAIR_BATCH]
            numbered = list(enumerate(batch, start=1))
            verdicts = relation_builder.review_pairs(
                pairs=numbered, relation=relation, client=llm_client
            )
            budget.spend()
            accepted = {verdict.pair_id for verdict in verdicts if verdict.accept}
            for index, pair in numbered:
                if index not in accepted:
                    continue
                plans.append(
                    _EdgePlan(
                        src_kp_id=pair.src_kp_id,
                        dst_kp_id=pair.dst_kp_id,
                        relation=relation,
                        weight=round(pair.cos, 4),
                        review_status=EdgeReviewStatus.PENDING.value,
                    )
                )
    return plans


def _dedupe(plans: Sequence[_EdgePlan]) -> list[_EdgePlan]:
    seen: set[tuple[int, int, str]] = set()
    result: list[_EdgePlan] = []
    for plan in plans:
        key = (plan.src_kp_id, plan.dst_kp_id, plan.relation)
        if key in seen:
            continue
        seen.add(key)
        result.append(plan)
    return result


def build(
    session: Session,
    *,
    subject_id: int,
    relations: Sequence[str] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    llm_client: LLMClient | None = None,
    embedder: Any | None = None,
) -> BuildSummary:
    """构建 subject 的关系边；不 commit（由 runner / CLI 提交）。"""
    from app.services.kp_align_service import ensure_kp_embeddings

    started = time.monotonic()
    wanted = tuple(relations) if relations else RELATIONS
    unknown = [item for item in wanted if item not in RELATIONS]
    if unknown:
        raise InvalidParamError(f"未知关系类型：{', '.join(unknown)}")

    ensure_kp_embeddings(session, subject_id=subject_id, embedder=embedder)
    nodes = _load_nodes(session, subject_id)
    brief_nodes = [
        KpBrief(
            kp_id=node.id,
            name=node.name,
            level=node.level,
            parent_id=node.parent_id,
            embedding=None,
        )
        for node in nodes
    ]
    paths = build_paths(brief_nodes)
    briefs = {node.id: _brief(node, paths.get(node.id, node.name)) for node in nodes}

    plans: list[_EdgePlan] = []
    if EdgeRelation.CONTAINS.value in wanted:
        plans.extend(_contains_plans(nodes))

    existing_edges = _load_edges(session, [node.id for node in nodes])
    known_pairs = direction_conflicts(
        [(edge.src_kp_id, edge.dst_kp_id, edge.relation) for edge in existing_edges]
    )

    budget = _CallBudget()
    if EdgeRelation.PREREQUISITE.value in wanted:
        plans.extend(
            _prereq_plans(
                nodes,
                briefs,
                paths,
                limit=limit,
                budget=budget,
                llm_client=llm_client,
                known_pairs=known_pairs,
            )
        )
    pair_relations = [
        relation
        for relation in (EdgeRelation.RELATED.value, EdgeRelation.CONFUSABLE.value)
        if relation in wanted
    ]
    if pair_relations:
        plans.extend(
            _pair_plans(briefs, pair_relations, budget=budget, llm_client=llm_client)
        )

    stats = _merge(session, _dedupe(plans), dry_run=dry_run)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    summary = BuildSummary(
        subject_id=subject_id,
        nodes=len(nodes),
        created=stats.created,
        updated=stats.updated,
        skipped_approved=stats.skipped_approved,
        skipped_rejected=stats.skipped_rejected,
        calls=budget.used,
        truncated=budget.exhausted,
        elapsed_ms=elapsed_ms,
    )
    logger.info(
        "graph_build_done",
        extra={
            "subject_id": subject_id,
            "nodes": summary.nodes,
            # 键名不能叫 created/updated：与 LogRecord 自带属性冲突会抛 KeyError
            "created_edges": summary.created,
            "updated_edges": summary.updated,
            "skipped_approved": summary.skipped_approved,
            "skipped_rejected": summary.skipped_rejected,
            "calls": summary.calls,
            "truncated": summary.truncated,
            "elapsed_ms": elapsed_ms,
        },
    )
    return summary


def _edge_names(session: Session, edges: Sequence[KnowledgeEdge]) -> dict[int, str]:
    ids = {edge.src_kp_id for edge in edges} | {edge.dst_kp_id for edge in edges}
    if not ids:
        return {}
    rows = session.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(ids)))
    return {row.id: row.name for row in rows}


def _apply_review(edge: KnowledgeEdge, *, approve: bool, reviewer: User) -> None:
    edge.review_status = (
        EdgeReviewStatus.APPROVED.value if approve else EdgeReviewStatus.REJECTED.value
    )
    edge.reviewed_by = reviewer.id
    edge.reviewed_at = datetime.now(timezone.utc)


def review_edge(
    session: Session, *, edge_id: int, approve: bool, reviewer: User
) -> KnowledgeEdge:
    edge = session.get(KnowledgeEdge, edge_id)
    if edge is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("关系边不存在或已被删除")
    _apply_review(edge, approve=approve, reviewer=reviewer)
    session.flush()
    return edge


def review_edges(
    session: Session, *, edge_ids: Sequence[int], approve: bool, reviewer: User
) -> tuple[int, int]:
    if not edge_ids:
        raise InvalidParamError("edge_ids 不能为空")
    updated = 0
    skipped = 0
    for edge_id in dict.fromkeys(edge_ids):
        edge = session.get(KnowledgeEdge, edge_id)
        if edge is None:
            skipped += 1
            continue
        _apply_review(edge, approve=approve, reviewer=reviewer)
        updated += 1
    session.flush()
    return updated, skipped


def stats(session: Session, *, subject_id: int | None) -> Any:
    from app.schemas.kp import GraphStatsOut

    node_stmt = select(func.count()).select_from(KnowledgePoint)
    if subject_id is not None:
        node_stmt = node_stmt.where(KnowledgePoint.subject_id == subject_id)
    nodes = int(session.scalar(node_stmt) or 0)

    edge_stmt = select(
        KnowledgeEdge.relation,
        KnowledgeEdge.review_status,
        func.count(),
        func.max(KnowledgeEdge.created_at),
    )
    if subject_id is not None:
        edge_stmt = edge_stmt.join(
            KnowledgePoint, KnowledgePoint.id == KnowledgeEdge.src_kp_id
        ).where(KnowledgePoint.subject_id == subject_id)
    rows = session.execute(edge_stmt.group_by(KnowledgeEdge.relation, KnowledgeEdge.review_status)).all()
    by_relation: dict[str, int] = {}
    by_status: dict[str, int] = {}
    last_built: datetime | None = None
    edges = 0
    for relation, status, count, newest in rows:
        by_relation[relation] = by_relation.get(relation, 0) + count
        by_status[status] = by_status.get(status, 0) + count
        edges += count
        if newest is not None and (last_built is None or newest > last_built):
            last_built = newest
    return GraphStatsOut(
        subject_id=subject_id,
        nodes=nodes,
        edges=edges,
        by_relation=by_relation,
        by_status=by_status,
        last_built_at=last_built,
    )


def edge_out(session: Session, edge: KnowledgeEdge) -> Any:
    from app.schemas.kp import GraphEdgeOut

    names = _edge_names(session, [edge])
    return GraphEdgeOut(
        id=edge.id,
        src_kp_id=edge.src_kp_id,
        src_name=names.get(edge.src_kp_id, f"#{edge.src_kp_id}"),
        dst_kp_id=edge.dst_kp_id,
        dst_name=names.get(edge.dst_kp_id, f"#{edge.dst_kp_id}"),
        relation=edge.relation,
        weight=float(edge.weight) if edge.weight is not None else None,
        source=edge.source,
        review_status=edge.review_status,
        reviewed_at=edge.reviewed_at,
        created_at=edge.created_at,
    )


def list_edges(
    session: Session,
    *,
    subject_id: int | None,
    status: str,
    relation: str | None,
    keyword: str | None,
    page: Any,
    sort: Any,
) -> Any:
    from fastapi_pagination import Params

    from app.schemas.kp import GraphEdgeOut, GraphEdgePage
    from app.utils.pagination import apply_sort, paginate_sa

    if status not in VALID_STATUSES:
        raise InvalidParamError(f"status 只能是 {sorted(VALID_STATUSES)}")
    stmt = select(KnowledgeEdge)
    if subject_id is not None:
        stmt = stmt.join(
            KnowledgePoint, KnowledgePoint.id == KnowledgeEdge.src_kp_id
        ).where(KnowledgePoint.subject_id == subject_id)
    if status != "all":
        stmt = stmt.where(KnowledgeEdge.review_status == status)
    if relation is not None:
        stmt = stmt.where(KnowledgeEdge.relation == relation)
    if keyword:
        like = f"%{keyword}%"
        matched = select(KnowledgePoint.id).where(KnowledgePoint.name.like(like))
        stmt = stmt.where(
            or_(
                KnowledgeEdge.src_kp_id.in_(matched),
                KnowledgeEdge.dst_kp_id.in_(matched),
            )
        )
    stmt = apply_sort(
        stmt,
        sort_by=sort.sort_by,
        order=sort.order,
        allowed=SORTABLE,
        default_sort="created_at",
    )
    # 不能用 paginate_query：它要求 Pydantic 的 item_model，而这里要先用两端名称补 DTO
    data = paginate_sa(
        session, stmt, params=Params(page=page.page, size=page.page_size)
    )
    names = _edge_names(session, list(data.items))
    items = [
        GraphEdgeOut(
            id=edge.id,
            src_kp_id=edge.src_kp_id,
            src_name=names.get(edge.src_kp_id, f"#{edge.src_kp_id}"),
            dst_kp_id=edge.dst_kp_id,
            dst_name=names.get(edge.dst_kp_id, f"#{edge.dst_kp_id}"),
            relation=edge.relation,
            weight=float(edge.weight) if edge.weight is not None else None,
            source=edge.source,
            review_status=edge.review_status,
            reviewed_at=edge.reviewed_at,
            created_at=edge.created_at,
        )
        for edge in data.items
    ]
    return GraphEdgePage(
        # fastapi-pagination 的 Page 用 size，不是 page_size（真机验收抓到）
        items=items,
        total=data.total,
        page=data.page,
        page_size=data.size,
    )


def enqueue_build(
    session: Session,
    *,
    owner: User,
    subject_id: int,
    relations: Sequence[str] | None,
    limit: int | None,
    queue: Any,
) -> Any:
    from app.services.task_service import create_task

    payload: dict[str, Any] = {"subject_id": subject_id}
    if relations:
        payload["relations"] = list(relations)
    if limit is not None:
        payload["limit"] = limit
    return create_task(
        session, owner=owner, name=TASK_BUILD_GRAPH, payload=payload, queue=queue
    )