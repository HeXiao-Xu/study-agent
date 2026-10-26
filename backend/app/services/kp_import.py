"""S2-9 知识点树导入：文件校验、扁平化、同步计划与落库。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.models.note_kp import NoteKp
from app.models.subject import Subject

ImportMode = Literal["append", "overwrite"]
MAX_LEVEL = 4


class SeedSubject(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=50)
    stage: str = "高中"


class SeedNode(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    exam_weight: float | None = Field(default=None, ge=0, le=1)
    order_no: int = Field(default=0, ge=0)
    children: list["SeedNode"] = Field(default_factory=list)


class TreeFile(BaseModel):
    subject: SeedSubject
    nodes: list[SeedNode]


class FlatSeed(BaseModel):
    code: str
    name: str
    level: int
    parent_code: str | None
    description: str | None = None
    exam_weight: float | None = None
    order_no: int = 0


class SyncPlan(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    created: list[FlatSeed] = Field(default_factory=list)
    updated: list[FlatSeed] = Field(default_factory=list)
    unchanged: list[FlatSeed] = Field(default_factory=list)
    deletes: list[KnowledgePoint] = Field(default_factory=list)
    skipped: list[tuple[str, str]] = Field(default_factory=list)


class ImportStats(BaseModel):
    created: int
    updated: int
    deleted: int
    skipped: int
    unchanged: int


class ImportResult(BaseModel):
    stats: ImportStats
    skipped: list[tuple[str, str]] = Field(default_factory=list)


def load_tree_file(path: str | Path) -> TreeFile:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"种子文件不存在: {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败: {exc.msg}（第 {exc.lineno} 行）") from exc
    try:
        return TreeFile.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ValueError(f"种子数据校验失败: {first.get('loc')} {first.get('msg')}") from exc


def flatten_tree(nodes: list[SeedNode]) -> list[FlatSeed]:
    flat: list[FlatSeed] = []
    seen: set[str] = set()

    def walk(items: list[SeedNode], level: int, parent_code: str | None) -> None:
        if not items:
            return
        if level > MAX_LEVEL:
            raise ValueError(f"知识点层级最多 {MAX_LEVEL} 级")
        for index, node in enumerate(items):
            if node.code in seen:
                raise ValueError(f"重复 code: {node.code}")
            seen.add(node.code)
            flat.append(
                FlatSeed(
                    code=node.code,
                    name=node.name,
                    level=level,
                    parent_code=parent_code,
                    description=node.description,
                    exam_weight=node.exam_weight,
                    order_no=node.order_no or index,
                )
            )
            walk(node.children, level + 1, node.code)

    walk(nodes, 1, None)
    return flat


def plan_sync(
    existing: list[KnowledgePoint],
    incoming: list[FlatSeed],
    *,
    referenced_codes: set[str],
    mode: ImportMode,
) -> SyncPlan:
    by_code = {row.code: row for row in existing}
    incoming_codes = {item.code for item in incoming}
    plan = SyncPlan()
    for item in incoming:
        row = by_code.get(item.code)
        if row is None:
            plan.created.append(item)
            continue
        parent = by_code.get(item.parent_code) if item.parent_code else None
        same_parent = (row.parent_id is None and item.parent_code is None) or (
            parent is not None and row.parent_id == parent.id
        )
        same = (
            row.name == item.name
            and row.description == item.description
            and _same_weight(row.exam_weight, item.exam_weight)
            and row.order_no == item.order_no
            and same_parent
        )
        if same:
            plan.unchanged.append(item)
        else:
            plan.updated.append(item)

    if mode == "overwrite":
        missing = [row for row in existing if row.code not in incoming_codes]
        remaining = {row.code for row in existing}
        for row in sorted(missing, key=lambda item: item.level, reverse=True):
            has_child = any(
                child.parent_id == row.id and child.code in remaining for child in existing
            )
            if has_child:
                plan.skipped.append((row.code, "has_children"))
                continue
            if row.code in referenced_codes:
                plan.skipped.append((row.code, "referenced"))
                continue
            plan.deletes.append(row)
            remaining.discard(row.code)
    return plan


def import_tree(
    session: Session,
    *,
    tree: TreeFile,
    mode: ImportMode = "append",
    dry_run: bool = False,
) -> ImportResult:
    flat = flatten_tree(tree.nodes)
    subject = session.scalar(select(Subject).where(Subject.code == tree.subject.code))
    if subject is None:
        subject = Subject(
            name=tree.subject.name, code=tree.subject.code, stage=tree.subject.stage
        )
        session.add(subject)
        session.flush()
    existing = list(
        session.scalars(
            select(KnowledgePoint).where(KnowledgePoint.subject_id == subject.id)
        )
    )
    referenced_ids: set[int] = set(session.scalars(select(NoteKp.kp_id)))
    referenced_ids.update(session.scalars(select(KnowledgeEdge.src_kp_id)))
    referenced_ids.update(session.scalars(select(KnowledgeEdge.dst_kp_id)))
    referenced = referenced_codes_for(existing, referenced_ids)
    plan = plan_sync(existing, flat, referenced_codes=referenced, mode=mode)
    if dry_run:
        return ImportResult(stats=_stats(plan), skipped=plan.skipped)

    by_code = {row.code: row for row in existing}
    code_to_id = {row.code: row.id for row in existing}
    for item in sorted(plan.created, key=lambda seed: seed.level):
        row = KnowledgePoint(
            subject_id=subject.id,
            parent_id=code_to_id.get(item.parent_code),
            name=item.name,
            code=item.code,
            level=item.level,
            description=item.description,
            exam_weight=item.exam_weight,
            order_no=item.order_no,
        )
        session.add(row)
        session.flush()
        code_to_id[item.code] = row.id
    for item in plan.updated:
        row = by_code[item.code]
        row.name = item.name
        row.description = item.description
        row.exam_weight = item.exam_weight
        row.order_no = item.order_no
        row.parent_id = code_to_id.get(item.parent_code)
        row.level = item.level
    for row in plan.deletes:
        session.delete(row)
    session.commit()
    return ImportResult(stats=_stats(plan), skipped=plan.skipped)


def referenced_codes_for(
    existing: list[KnowledgePoint], referenced_ids: set[int]
) -> set[str]:
    return {row.code for row in existing if row.id in referenced_ids}


def _stats(plan: SyncPlan) -> ImportStats:
    return ImportStats(
        created=len(plan.created),
        updated=len(plan.updated),
        deleted=len(plan.deletes),
        skipped=len(plan.skipped),
        unchanged=len(plan.unchanged),
    )


def _same_weight(left: object, right: float | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return float(left) == float(right)