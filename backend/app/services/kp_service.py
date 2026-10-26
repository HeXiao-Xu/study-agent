"""S2-9 知识点树服务：一次查询组树、level 推导、删除保护。"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, InvalidParamError, NotFoundError
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.models.note_kp import NoteKp
from app.models.subject import Subject
from app.schemas.kp import KpCreate, KpNodeOut, KpTreeOut, KpUpdate, SubjectOut

MAX_LEVEL = 4


def list_subjects(session: Session) -> list[Subject]:
    return list(session.scalars(select(Subject).order_by(Subject.id)))


def get_tree(session: Session, *, subject_code: str) -> KpTreeOut:
    subject = session.scalar(select(Subject).where(Subject.code == subject_code))
    if subject is None:
        raise NotFoundError("学科不存在")
    rows = list(
        session.scalars(
            select(KnowledgePoint)
            .where(KnowledgePoint.subject_id == subject.id)
            .order_by(KnowledgePoint.level, KnowledgePoint.order_no, KnowledgePoint.id)
        )
    )
    nodes: dict[int, KpNodeOut] = {row.id: KpNodeOut.model_validate(row) for row in rows}
    children: dict[int | None, list[KpNodeOut]] = defaultdict(list)
    for row in rows:
        children[row.parent_id].append(nodes[row.id])
    for node_id, node in nodes.items():
        node.children = children.get(node_id, [])
    return KpTreeOut(
        subject=SubjectOut.model_validate(subject),
        nodes=children.get(None, []),
    )


def create_kp(session: Session, *, payload: KpCreate) -> KnowledgePoint:
    subject = session.scalar(select(Subject).where(Subject.code == payload.subject))
    if subject is None:
        raise NotFoundError("学科不存在")
    level = 1
    if payload.parent_id is not None:
        parent = session.get(KnowledgePoint, payload.parent_id)
        if parent is None:
            raise NotFoundError("父节点不存在")
        if parent.subject_id != subject.id:
            raise InvalidParamError("父节点不属于同一学科")
        level = parent.level + 1
        if level > MAX_LEVEL:
            raise InvalidParamError(f"知识点层级最多 {MAX_LEVEL} 级")
    if (
        session.scalar(
            select(KnowledgePoint.id).where(
                KnowledgePoint.subject_id == subject.id,
                KnowledgePoint.code == payload.code,
            )
        )
        is not None
    ):
        raise ConflictError("知识点编码已存在")
    kp = KnowledgePoint(
        subject_id=subject.id,
        parent_id=payload.parent_id,
        name=payload.name,
        code=payload.code,
        level=level,
        description=payload.description,
        exam_weight=payload.exam_weight,
        order_no=payload.order_no,
    )
    session.add(kp)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("知识点编码已存在") from exc
    session.commit()
    session.refresh(kp)
    return kp


def update_kp(session: Session, *, kp_id: int, payload: KpUpdate) -> KnowledgePoint:
    kp = session.get(KnowledgePoint, kp_id)
    if kp is None:
        raise NotFoundError("知识点不存在")
    data = payload.model_dump(exclude_unset=True)

    if "parent_id" in data:
        new_parent_id = data["parent_id"]
        rows = list(
            session.scalars(
                select(KnowledgePoint).where(KnowledgePoint.subject_id == kp.subject_id)
            )
        )
        by_id = {row.id: row for row in rows}
        if new_parent_id is None:
            new_level = 1
        else:
            parent = by_id.get(new_parent_id) or session.get(KnowledgePoint, new_parent_id)
            if parent is None:
                raise NotFoundError("父节点不存在")
            if parent.subject_id != kp.subject_id:
                raise InvalidParamError("父节点不属于同一学科")
            if parent.id == kp.id:
                raise InvalidParamError("父节点不能是自身")
            cursor = parent
            while cursor is not None:
                if cursor.id == kp.id:
                    raise InvalidParamError("不能移动到自己的子节点下")
                cursor = by_id.get(cursor.parent_id)
            new_level = parent.level + 1
        height = _subtree_height(rows, kp.id)
        if new_level + height - 1 > MAX_LEVEL:
            raise InvalidParamError(f"移动后子树超过 {MAX_LEVEL} 级")
        kp.parent_id = new_parent_id
        kp.level = new_level
        _reassign_descendant_levels(rows, kp)

    for field in ("name", "description", "exam_weight", "order_no"):
        if field in data:
            setattr(kp, field, data[field])
    session.commit()
    session.refresh(kp)
    return kp


def delete_kp(session: Session, *, kp_id: int) -> None:
    kp = session.get(KnowledgePoint, kp_id)
    if kp is None:
        raise NotFoundError("知识点不存在")
    if (
        session.scalar(
            select(KnowledgePoint.id)
            .where(KnowledgePoint.parent_id == kp_id)
            .limit(1)
        )
        is not None
    ):
        raise ConflictError("存在子知识点，请先删除子节点")
    if session.scalar(select(NoteKp.note_id).where(NoteKp.kp_id == kp_id).limit(1)) is not None:
        raise ConflictError("已被笔记引用，无法删除")
    if (
        session.scalar(
            select(KnowledgeEdge.id)
            .where(
                or_(
                    KnowledgeEdge.src_kp_id == kp_id,
                    KnowledgeEdge.dst_kp_id == kp_id,
                )
            )
            .limit(1)
        )
        is not None
    ):
        raise ConflictError("存在知识点关系引用，无法删除")
    session.delete(kp)
    session.commit()


def _subtree_height(rows: list[KnowledgePoint], root_id: int) -> int:
    children: dict[int, list[KnowledgePoint]] = defaultdict(list)
    for row in rows:
        if row.parent_id is not None:
            children[row.parent_id].append(row)
    height = 0
    frontier = [root_id]
    while frontier:
        height += 1
        frontier = [child.id for node_id in frontier for child in children.get(node_id, [])]
    return height


def _reassign_descendant_levels(rows: list[KnowledgePoint], root: KnowledgePoint) -> None:
    children: dict[int, list[KnowledgePoint]] = defaultdict(list)
    for row in rows:
        if row.parent_id is not None:
            children[row.parent_id].append(row)
    frontier = [(child, root.level + 1) for child in children.get(root.id, [])]
    while frontier:
        node, level = frontier.pop()
        node.level = level
        frontier.extend((child, level + 1) for child in children.get(node.id, []))