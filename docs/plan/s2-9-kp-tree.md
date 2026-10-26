# S2-9 知识点树 CRUD + 导入脚本 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付知识点树读/建/改/删接口与 append/overwrite 导入脚本，并导入一份 4 层、≥100 节点的高中数学种子树。

**Architecture:** `kp_service` 负责树查询（一次查完内存组树）、level 推导、移动校验与删除保护；`kp_import` 把“读文件/校验/计划同步/落库”拆开，`plan_sync` 是纯函数便于单测；CLI 只做参数解析与统计输出。

**Tech Stack:** FastAPI、SQLAlchemy 2.1、Pydantic 2、PostgreSQL 16（现有 `subjects`/`knowledge_points`/`note_kps`/`knowledge_edges`）、pytest。

**Spec:** `docs/spec/s2-9-kp-tree.md`

## Global Constraints

- **不新增迁移**：`knowledge_points` 字段已齐；`subjects` 由导入脚本创建 `math`。
- 树查询必须一次 SQL 查完再内存组树，禁止 N+1 递归。
- `level` 只由父节点推导：根 1、最深 4；PATCH 移动节点必须检查环与子树高度。
- `code` 不可修改；`(subject_id, code)` 冲突 → `40900`。
- 删除保护顺序：子节点 → `note_kps` → `knowledge_edges`，冲突一律 409 并给可读 message。
- 写接口 `require_role("admin", "teacher")`；读接口 `get_current_user`。
- 导入 `overwrite` 删除按 level 降序；有保留子节点或被引用 → 保留并计入 skipped。
- 测试禁止真实 DB/网络：`FakeSession` 按 SQL 文本分派实体。
- 提交信息带 `(s2-9)`；`git push` 由用户执行。

---

### Task 1: schemas + kp_service CRUD

**Files:**
- Create: `backend/app/schemas/kp.py`
- Create: `backend/app/services/kp_service.py`
- Test: `backend/tests/test_kp_service.py`

**Interfaces:**
- Consumes: `Subject`、`KnowledgePoint`、`NoteKp`、`KnowledgeEdge`、`NotFoundError`/`ConflictError`/`InvalidParamError`
- Produces: `SubjectOut`、`KpNodeOut`、`KpTreeOut`、`KpCreate`、`KpUpdate`；`list_subjects/get_tree/create_kp/update_kp/delete_kp`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_kp_service.py`：

```python
"""S2-9 知识点服务：FakeSession，按 SQL 文本分派实体。"""
from __future__ import annotations

import pytest

from app.core.exceptions import ConflictError, InvalidParamError, NotFoundError
from app.models.knowledge_point import KnowledgePoint
from app.models.subject import Subject
from app.schemas.kp import KpCreate, KpUpdate
from app.services import kp_service


class FakeSession:
    def __init__(
        self,
        *,
        subject: Subject | None = None,
        rows: list[KnowledgePoint] | None = None,
        get_map: dict[int, KnowledgePoint] | None = None,
        duplicate: bool = False,
        has_child: bool = False,
        note_ref: bool = False,
        edge_ref: bool = False,
    ) -> None:
        self.subject = subject
        self.rows = rows or []
        self.get_map = get_map or {}
        self.duplicate = duplicate
        self.has_child = has_child
        self.note_ref = note_ref
        self.edge_ref = edge_ref
        self.scalars_calls = 0
        self.added: list[KnowledgePoint] = []
        self.deleted: list[KnowledgePoint] = []
        self.commits = 0

    def scalar(self, statement: object):
        sql = str(statement)
        if "FROM subjects" in sql:
            return self.subject
        if "FROM note_kps" in sql:
            return 1 if self.note_ref else None
        if "FROM knowledge_edges" in sql:
            return 1 if self.edge_ref else None
        if "FROM knowledge_points" in sql:
            if "parent_id" in sql:
                return 1 if self.has_child else None
            return 1 if self.duplicate else None
        raise AssertionError(f"unexpected SQL: {sql}")

    def scalars(self, statement: object):
        self.scalars_calls += 1
        return list(self.rows)

    def get(self, entity: type, pk: int):
        if entity is KnowledgePoint:
            return self.get_map.get(pk)
        raise AssertionError(f"unexpected get: {entity}")

    def add(self, instance: KnowledgePoint) -> None:
        self.added.append(instance)

    def flush(self) -> None:
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = 100

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def refresh(self, instance: object) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = 100

    def delete(self, instance: KnowledgePoint) -> None:
        self.deleted.append(instance)


def _subject(subject_id: int = 1, code: str = "math") -> Subject:
    subject = Subject(name="高中数学", code=code, stage="高中")
    subject.id = subject_id
    return subject


def _kp(
    kp_id: int,
    code: str,
    level: int,
    parent_id: int | None,
    *,
    subject_id: int = 1,
    name: str | None = None,
    order_no: int = 0,
) -> KnowledgePoint:
    kp = KnowledgePoint(
        subject_id=subject_id,
        parent_id=parent_id,
        name=name or code,
        code=code,
        level=level,
        description=None,
        exam_weight=None,
        order_no=order_no,
    )
    kp.id = kp_id
    return kp


def test_get_tree_builds_children_in_one_query() -> None:
    root = _kp(1, "MATH", 1, None)
    child = _kp(2, "MATH-SET", 2, 1, order_no=1)
    leaf = _kp(3, "MATH-SET-01", 3, 2, order_no=1)
    sibling = _kp(4, "MATH-SET-02", 3, 2, order_no=2)
    session = FakeSession(subject=_subject(), rows=[root, child, leaf, sibling])
    tree = kp_service.get_tree(session, subject_code="math")  # type: ignore[arg-type]
    assert tree.subject.code == "math"
    assert len(tree.nodes) == 1
    assert [node.code for node in tree.nodes[0].children] == ["MATH-SET"]
    assert [node.code for node in tree.nodes[0].children[0].children] == [
        "MATH-SET-01",
        "MATH-SET-02",
    ]
    assert session.scalars_calls == 1


def test_get_tree_missing_subject_raises_not_found() -> None:
    with pytest.raises(NotFoundError, match="学科不存在"):
        kp_service.get_tree(FakeSession(), subject_code="nope")  # type: ignore[arg-type]


def test_create_kp_root_gets_level_one() -> None:
    session = FakeSession(subject=_subject())
    kp = kp_service.create_kp(
        session,  # type: ignore[arg-type]
        payload=KpCreate(subject="math", code="MATH-X", name="新根节点"),
    )
    assert kp.level == 1
    assert kp.parent_id is None
    assert session.added == [kp]
    assert session.commits == 1


def test_create_kp_child_level_is_parent_plus_one() -> None:
    parent = _kp(1, "MATH", 1, None)
    session = FakeSession(subject=_subject(), get_map={1: parent})
    kp = kp_service.create_kp(
        session,  # type: ignore[arg-type]
        payload=KpCreate(subject="math", parent_id=1, code="MATH-X", name="子节点"),
    )
    assert kp.level == 2
    assert kp.parent_id == 1


def test_create_kp_beyond_level_four_raises() -> None:
    parent = _kp(4, "MATH-L4", 4, 3)
    session = FakeSession(subject=_subject(), get_map={4: parent})
    with pytest.raises(InvalidParamError, match="最多 4 级"):
        kp_service.create_kp(
            session,  # type: ignore[arg-type]
            payload=KpCreate(subject="math", parent_id=4, code="MATH-L5", name="第五层"),
        )


def test_create_kp_duplicate_code_raises_conflict() -> None:
    session = FakeSession(subject=_subject(), duplicate=True)
    with pytest.raises(ConflictError, match="编码已存在"):
        kp_service.create_kp(
            session,  # type: ignore[arg-type]
            payload=KpCreate(subject="math", code="MATH", name="重复"),
        )


def test_create_kp_cross_subject_parent_raises() -> None:
    parent = _kp(1, "OTHER", 1, None, subject_id=2)
    session = FakeSession(subject=_subject(), get_map={1: parent})
    with pytest.raises(InvalidParamError, match="同一学科"):
        kp_service.create_kp(
            session,  # type: ignore[arg-type]
            payload=KpCreate(subject="math", parent_id=1, code="MATH-X", name="跨学科"),
        )


def test_update_kp_renames_and_sets_weight() -> None:
    kp = _kp(1, "MATH", 1, None)
    session = FakeSession(get_map={1: kp})
    updated = kp_service.update_kp(
        session,  # type: ignore[arg-type]
        kp_id=1,
        payload=KpUpdate(name="高中数学（改）", exam_weight=0.9),
    )
    assert updated.name == "高中数学（改）"
    assert float(updated.exam_weight) == 0.9
    assert session.commits == 1


def test_update_kp_cycle_parent_raises() -> None:
    root = _kp(1, "MATH", 1, None)
    child = _kp(2, "MATH-SET", 2, 1)
    leaf = _kp(3, "MATH-SET-01", 3, 2)
    session = FakeSession(rows=[root, child, leaf], get_map={1: root, 2: child, 3: leaf})
    with pytest.raises(InvalidParamError, match="子节点"):
        kp_service.update_kp(session, kp_id=1, payload=KpUpdate(parent_id=3))  # type: ignore[arg-type]


def test_update_kp_move_keeps_subtree_within_four_levels() -> None:
    target = _kp(1, "MATH-A", 1, None)
    moving = _kp(2, "MATH-B", 2, 1)
    child = _kp(3, "MATH-B-01", 3, 2)
    session = FakeSession(rows=[target, moving, child], get_map={1: target, 2: moving})
    with pytest.raises(InvalidParamError, match="超过 4 级"):
        kp_service.update_kp(session, kp_id=2, payload=KpUpdate(parent_id=1))  # type: ignore[arg-type]


def test_update_kp_move_recalculates_descendant_levels() -> None:
    moving = _kp(1, "MATH-A", 1, None)
    child = _kp(2, "MATH-A-01", 2, 1)
    grand = _kp(3, "MATH-A-01-01", 3, 2)
    new_parent = _kp(4, "MATH-B", 1, None)
    session = FakeSession(
        rows=[moving, child, grand, new_parent],
        get_map={1: moving, 4: new_parent},
    )
    updated = kp_service.update_kp(session, kp_id=1, payload=KpUpdate(parent_id=4))  # type: ignore[arg-type]
    assert updated.parent_id == 4
    assert updated.level == 2
    assert child.level == 3
    assert grand.level == 4


def test_delete_kp_blocks_children_references_then_deletes_leaf() -> None:
    kp = _kp(1, "MATH-L", 1, None)
    with pytest.raises(ConflictError, match="子知识点"):
        kp_service.delete_kp(FakeSession(get_map={1: kp}, has_child=True), kp_id=1)  # type: ignore[arg-type]
    with pytest.raises(ConflictError, match="笔记引用"):
        kp_service.delete_kp(FakeSession(get_map={1: kp}, note_ref=True), kp_id=1)  # type: ignore[arg-type]
    with pytest.raises(ConflictError, match="关系引用"):
        kp_service.delete_kp(FakeSession(get_map={1: kp}, edge_ref=True), kp_id=1)  # type: ignore[arg-type]
    session = FakeSession(get_map={1: kp})
    kp_service.delete_kp(session, kp_id=1)  # type: ignore[arg-type]
    assert session.deleted == [kp]
    assert session.commits == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_kp_service.py -q`
Expected: FAIL，`ModuleNotFoundError: app.schemas.kp`

- [ ] **Step 3: 实现 schemas**

`backend/app/schemas/kp.py`：

```python
"""S2-9 知识点出入参（API.md §4）。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    stage: str


class KpNodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    parent_id: int | None
    name: str
    code: str
    level: int
    description: str | None
    exam_weight: float | None
    order_no: int
    children: list["KpNodeOut"] = Field(default_factory=list)


class KpTreeOut(BaseModel):
    subject: SubjectOut
    nodes: list[KpNodeOut]


class KpCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=30, description="学科 code")
    parent_id: int | None = Field(default=None, ge=1)
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    exam_weight: float | None = Field(default=None, ge=0, le=1)
    order_no: int = Field(default=0, ge=0)


class KpUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    exam_weight: float | None = Field(default=None, ge=0, le=1)
    order_no: int | None = Field(default=None, ge=0)
    parent_id: int | None = Field(default=None, ge=1)
```

- [ ] **Step 4: 实现 service**

`backend/app/services/kp_service.py`：

```python
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
    nodes: dict[int, KpNodeOut] = {
        row.id: KpNodeOut.model_validate(row) for row in rows
    }
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
    if session.scalar(
        select(KnowledgePoint.id).where(
            KnowledgePoint.subject_id == subject.id,
            KnowledgePoint.code == payload.code,
        )
    ) is not None:
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
    if session.scalar(
        select(KnowledgePoint.id)
        .where(KnowledgePoint.parent_id == kp_id)
        .limit(1)
    ) is not None:
        raise ConflictError("存在子知识点，请先删除子节点")
    if session.scalar(select(NoteKp.note_id).where(NoteKp.kp_id == kp_id).limit(1)) is not None:
        raise ConflictError("已被笔记引用，无法删除")
    if session.scalar(
        select(KnowledgeEdge.id)
        .where(or_(KnowledgeEdge.src_kp_id == kp_id, KnowledgeEdge.dst_kp_id == kp_id))
        .limit(1)
    ) is not None:
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
```

> 注：`_subtree_height` 的 `while` 按层计数，叶子返回 1。

- [ ] **Step 5: 运行服务测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_kp_service.py -q`
Expected: `12 passed`

- [ ] **Step 6: 提交**

```bash
git add backend/app/schemas/kp.py backend/app/services/kp_service.py backend/tests/test_kp_service.py
git commit -m "feat(s2-9): 知识点树服务与校验"
```

---

### Task 2: 导入计划与落库

**Files:**
- Create: `backend/app/services/kp_import.py`
- Test: `backend/tests/test_kp_import.py`

**Interfaces:**
- Consumes: `KnowledgePoint`、`Subject`、`NoteKp`、`KnowledgeEdge`
- Produces: `SeedNode`/`TreeFile`/`FlatSeed`/`SyncPlan`/`ImportStats`、`load_tree_file`、`flatten_tree`、`plan_sync`、`import_tree`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_kp_import.py`：

```python
"""S2-9 导入：文件校验/扁平化/同步计划为纯函数，不连库。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.knowledge_point import KnowledgePoint
from app.services.kp_import import (
    FlatSeed,
    TreeFile,
    flatten_tree,
    load_tree_file,
    plan_sync,
)


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "tree.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _tree_payload(children: list[dict] | None = None) -> dict:
    return {
        "subject": {"code": "math", "name": "高中数学"},
        "nodes": [
            {
                "code": "MATH",
                "name": "高中数学",
                "description": "根",
                "exam_weight": 1.0,
                "children": children or [],
            }
        ],
    }


def _kp(code: str, kp_id: int, parent_id: int | None = None, level: int = 1) -> KnowledgePoint:
    kp = KnowledgePoint(
        subject_id=1,
        parent_id=parent_id,
        name=code,
        code=code,
        level=level,
        description=None,
        exam_weight=None,
        order_no=0,
    )
    kp.id = kp_id
    return kp


def test_load_tree_file_parses_nested_nodes(tmp_path: Path) -> None:
    path = _write(tmp_path, _tree_payload([{"code": "MATH-A", "name": "模块"}]))
    tree = load_tree_file(path)
    assert isinstance(tree, TreeFile)
    assert tree.subject.code == "math"
    assert tree.nodes[0].children[0].code == "MATH-A"


def test_load_tree_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_tree_file(tmp_path / "nope.json")


def test_load_tree_file_invalid_json_raises_value_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        load_tree_file(path)


def test_load_tree_file_schema_error_raises_value_error(tmp_path: Path) -> None:
    path = _write(tmp_path, {"subject": {"code": "math", "name": "高中数学"}, "nodes": [{"name": "缺 code"}]})
    with pytest.raises(ValueError, match="校验失败"):
        load_tree_file(path)


def test_flatten_tree_rejects_duplicate_codes(tmp_path: Path) -> None:
    tree = load_tree_file(
        _write(
            tmp_path,
            _tree_payload(
                [
                    {"code": "MATH-A", "name": "A"},
                    {"code": "MATH-A", "name": "A2"},
                ]
            ),
        )
    )
    with pytest.raises(ValueError, match="重复 code"):
        flatten_tree(tree.nodes)


def test_flatten_tree_rejects_depth_five() -> None:
    node = {"code": "L5", "name": "L5"}
    for level in (4, 3, 2, 1):
        node = {"code": f"L{level}", "name": f"L{level}", "children": [node]}
    tree = TreeFile.model_validate({"subject": {"code": "math", "name": "数学"}, "nodes": [node]})
    with pytest.raises(ValueError, match="4 级"):
        flatten_tree(tree.nodes)


def test_flatten_tree_sets_parent_code_level_and_order(tmp_path: Path) -> None:
    tree = load_tree_file(
        _write(
            tmp_path,
            _tree_payload(
                [
                    {"code": "MATH-A", "name": "A", "children": [{"code": "MATH-A-01", "name": "A1"}]},
                    {"code": "MATH-B", "name": "B"},
                ]
            ),
        )
    )
    flat = flatten_tree(tree.nodes)
    by_code = {item.code: item for item in flat}
    assert by_code["MATH"].level == 1
    assert by_code["MATH-A"].parent_code == "MATH"
    assert by_code["MATH-A"].level == 2
    assert by_code["MATH-A-01"].level == 3
    assert by_code["MATH-B"].order_no == 1


def test_plan_sync_append_classifies_create_update_unchanged() -> None:
    flat = [
        FlatSeed(code="MATH", name="高中数学", level=1, parent_code=None, order_no=0),
        FlatSeed(code="MATH-A", name="新名字", level=2, parent_code="MATH", order_no=1),
    ]
    existing = [_kp("MATH", 1), _kp("MATH-A", 2, parent_id=1, level=2)]
    existing[0].name = "高中数学"
    existing[1].name = "旧名字"
    plan = plan_sync(existing, flat, referenced_codes=set(), mode="append")
    assert [item.code for item in plan.created] == []
    assert [item.code for item in plan.updated] == ["MATH-A"]
    assert plan.deletes == []


def test_plan_sync_overwrite_deletes_missing_leaf() -> None:
    flat = [FlatSeed(code="MATH", name="高中数学", level=1, parent_code=None, order_no=0)]
    existing = [_kp("MATH", 1), _kp("MATH-A", 2, parent_id=1, level=2)]
    plan = plan_sync(existing, flat, referenced_codes=set(), mode="overwrite")
    assert [row.code for row in plan.deletes] == ["MATH-A"]


def test_plan_sync_overwrite_skips_children_and_referenced() -> None:
    flat = [FlatSeed(code="MATH", name="高中数学", level=1, parent_code=None, order_no=0)]
    existing = [_kp("MATH", 1), _kp("MATH-A", 2, parent_id=1, level=2)]
    plan = plan_sync(existing, flat, referenced_codes={"MATH-A"}, mode="overwrite")
    assert plan.deletes == []
    assert plan.skipped == [("MATH-A", "referenced")]
```

> `Test 6` 只覆盖深度错误；`test_plan_sync_overwrite_skips_children_and_referenced` 同时覆盖子节点与引用两种原因（子节点保留 → 父节点 skip has_children；叶子 referenced → skip referenced）。再补一例断言 `skip has_children` 的父节点：

```python
def test_plan_sync_overwrite_skips_parent_with_kept_child() -> None:
    flat = [
        FlatSeed(code="MATH", name="高中数学", level=1, parent_code=None, order_no=0),
        FlatSeed(code="MATH-A-01", name="A1", level=3, parent_code="MATH-A", order_no=1),
    ]
    existing = [
        _kp("MATH", 1),
        _kp("MATH-A", 2, parent_id=1, level=2),
        _kp("MATH-A-01", 3, parent_id=2, level=3),
    ]
    plan = plan_sync(existing, flat, referenced_codes=set(), mode="overwrite")
    # MATH-A-01 保留在 incoming，所以 MATH-A 仍有子节点；但 MATH-A 不在 incoming 且其子节点仍在
    assert [row.code for row in plan.deletes] == []
    assert ("MATH-A", "has_children") in plan.skipped
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_kp_import.py -q`
Expected: FAIL，`ModuleNotFoundError: app.services.kp_import`

- [ ] **Step 3: 实现 kp_import**

`backend/app/services/kp_import.py`：

```python
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
    created: list[FlatSeed] = Field(default_factory=list)
    updated: list[FlatSeed] = Field(default_factory=list)
    unchanged: list[FlatSeed] = Field(default_factory=list)
    deletes: list[KnowledgePoint] = Field(default_factory=list)
    skipped: list[tuple[str, str]] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


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
    referenced: set[str] = set(session.scalars(select(NoteKp.kp_id)))
    referenced.update(session.scalars(select(KnowledgeEdge.src_kp_id)))
    referenced.update(session.scalars(select(KnowledgeEdge.dst_kp_id)))
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
```

- [ ] **Step 4: 运行导入测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_kp_import.py -q`
Expected: `11 passed`（10 条基础 + 1 条 has_children）

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/kp_import.py backend/tests/test_kp_import.py
git commit -m "feat(s2-9): 知识点导入同步计划与落库"
```

---

### Task 3: 种子数据与 CLI

**Files:**
- Create: `backend/data/kp_math.json`
- Create: `backend/scripts/import_kp_tree.py`
- Test: `backend/tests/test_kp_seed.py`

**Interfaces:**
- Consumes: `load_tree_file`/`flatten_tree`/`import_tree`
- Produces: 108 节点高中数学树；`scripts/import_kp_tree.py` CLI（`--file/--mode/--dry-run`）

- [ ] **Step 1: 生成种子 JSON**

`backend/data/kp_math.json`（完整内容，逐节点一行以免 diff 噪声）：

```python
# 运行一次生成本数据文件；之后以 JSON 为准人工校对（脚本不提交）
import json
from pathlib import Path

TREE = {
    "MATH": ("高中数学", 1.0, {
        "MATH-SET": ("集合与常用逻辑用语", 0.8, {
            "MATH-SET-01": ("集合的概念与表示", 0.6, {}),
            "MATH-SET-02": ("集合间的基本关系", 0.6, {}),
            "MATH-SET-03": ("集合的基本运算", 0.7, {}),
            "MATH-SET-04": ("充分条件与必要条件", 0.7, {}),
            "MATH-SET-05": ("全称量词与存在量词", 0.5, {}),
        }),
        "MATH-QUAD": ("一元二次函数、方程和不等式", 0.8, {
            "MATH-QUAD-01": ("等式性质与不等式性质", 0.6, {}),
            "MATH-QUAD-02": ("基本不等式", 0.7, {}),
            "MATH-QUAD-03": ("一元二次函数", 0.7, {}),
            "MATH-QUAD-04": ("一元二次方程", 0.6, {}),
            "MATH-QUAD-05": ("一元二次不等式", 0.7, {}),
        }),
        "MATH-FUNC": ("函数", 1.0, {
            "MATH-FUNC-01": ("函数的概念及其表示", 0.8, {
                "MATH-FUNC-01-01": ("定义域与值域", 0.6, {}),
                "MATH-FUNC-01-02": ("分段函数", 0.5, {}),
            }),
            "MATH-FUNC-02": ("函数的单调性", 0.9, {
                "MATH-FUNC-02-01": ("单调性的判断与证明", 0.7, {}),
            }),
            "MATH-FUNC-03": ("函数的奇偶性", 0.8, {}),
            "MATH-FUNC-04": ("函数的周期性与对称性", 0.6, {}),
            "MATH-FUNC-05": ("幂函数", 0.5, {}),
            "MATH-FUNC-06": ("指数函数", 0.8, {}),
            "MATH-FUNC-07": ("对数函数", 0.8, {}),
            "MATH-FUNC-08": ("函数图象变换", 0.6, {}),
            "MATH-FUNC-09": ("函数零点与二分法", 0.7, {}),
            "MATH-FUNC-10": ("函数模型及其应用", 0.6, {}),
        }),
        "MATH-TRIG": ("三角函数", 1.0, {
            "MATH-TRIG-01": ("任意角与弧度制", 0.5, {}),
            "MATH-TRIG-02": ("三角函数的定义与同角关系", 0.7, {
                "MATH-TRIG-02-01": ("同角三角函数基本关系", 0.5, {}),
            }),
            "MATH-TRIG-03": ("诱导公式", 0.6, {}),
            "MATH-TRIG-04": ("三角恒等变换", 0.9, {
                "MATH-TRIG-04-01": ("两角和与差公式", 0.7, {}),
                "MATH-TRIG-04-02": ("二倍角公式", 0.7, {}),
                "MATH-TRIG-04-03": ("辅助角公式", 0.6, {}),
            }),
            "MATH-TRIG-05": ("三角函数的图象与性质", 0.8, {}),
            "MATH-TRIG-06": ("函数 y=Asin(ωx+φ)", 0.8, {}),
            "MATH-TRIG-07": ("解三角形", 0.9, {
                "MATH-TRIG-07-01": ("正弦定理", 0.7, {}),
                "MATH-TRIG-07-02": ("余弦定理", 0.7, {}),
                "MATH-TRIG-07-03": ("三角形面积公式", 0.5, {}),
            }),
        }),
        "MATH-VEC": ("平面向量与复数", 0.8, {
            "MATH-VEC-01": ("向量的概念与线性运算", 0.6, {}),
            "MATH-VEC-02": ("平面向量基本定理与坐标表示", 0.7, {}),
            "MATH-VEC-03": ("平面向量的数量积", 0.8, {}),
            "MATH-VEC-04": ("向量的应用", 0.6, {}),
            "MATH-VEC-05": ("复数的概念与运算", 0.6, {}),
            "MATH-VEC-06": ("复数的几何意义", 0.5, {}),
        }),
        "MATH-SEQ": ("数列", 0.9, {
            "MATH-SEQ-01": ("数列的概念与表示", 0.5, {}),
            "MATH-SEQ-02": ("等差数列", 0.9, {
                "MATH-SEQ-02-01": ("通项公式与性质", 0.7, {}),
                "MATH-SEQ-02-02": ("前 n 项和", 0.7, {}),
            }),
            "MATH-SEQ-03": ("等比数列", 0.9, {
                "MATH-SEQ-03-01": ("通项公式与性质", 0.7, {}),
                "MATH-SEQ-03-02": ("前 n 项和", 0.7, {}),
            }),
            "MATH-SEQ-04": ("数列求和", 0.8, {}),
            "MATH-SEQ-05": ("递推数列与通项", 0.7, {}),
            "MATH-SEQ-06": ("数学归纳法", 0.5, {}),
        }),
        "MATH-GEO": ("立体几何", 0.9, {
            "MATH-GEO-01": ("空间几何体", 0.7, {
                "MATH-GEO-01-01": ("表面积与体积", 0.6, {}),
            }),
            "MATH-GEO-02": ("点、直线、平面的位置关系", 0.7, {}),
            "MATH-GEO-03": ("平行的判定与性质", 0.8, {}),
            "MATH-GEO-04": ("垂直的判定与性质", 0.8, {}),
            "MATH-GEO-05": ("空间向量及其应用", 0.8, {}),
            "MATH-GEO-06": ("空间角与距离", 0.8, {}),
        }),
        "MATH-ANA": ("解析几何", 1.0, {
            "MATH-ANA-01": ("直线的方程", 0.7, {}),
            "MATH-ANA-02": ("圆的方程", 0.7, {}),
            "MATH-ANA-03": ("椭圆", 0.9, {
                "MATH-ANA-03-01": ("定义与标准方程", 0.7, {}),
                "MATH-ANA-03-02": ("几何性质", 0.7, {}),
            }),
            "MATH-ANA-04": ("双曲线", 0.8, {
                "MATH-ANA-04-01": ("定义与标准方程", 0.6, {}),
                "MATH-ANA-04-02": ("几何性质", 0.6, {}),
            }),
            "MATH-ANA-05": ("抛物线", 0.8, {
                "MATH-ANA-05-01": ("定义与标准方程", 0.6, {}),
                "MATH-ANA-05-02": ("几何性质", 0.6, {}),
            }),
            "MATH-ANA-06": ("直线与圆锥曲线的位置关系", 0.9, {}),
            "MATH-ANA-07": ("参数方程与极坐标", 0.5, {}),
        }),
        "MATH-DER": ("导数及其应用", 1.0, {
            "MATH-DER-01": ("导数的概念与运算", 0.8, {
                "MATH-DER-01-01": ("基本求导公式", 0.6, {}),
                "MATH-DER-01-02": ("复合函数求导", 0.6, {}),
            }),
            "MATH-DER-02": ("导数与函数的单调性", 0.9, {}),
            "MATH-DER-03": ("函数的极值与最值", 0.9, {}),
            "MATH-DER-04": ("导数与不等式", 0.8, {}),
            "MATH-DER-05": ("导数的实际应用", 0.6, {}),
        }),
        "MATH-PROB": ("概率与统计", 0.9, {
            "MATH-PROB-01": ("随机事件与概率", 0.6, {}),
            "MATH-PROB-02": ("古典概型", 0.7, {}),
            "MATH-PROB-03": ("条件概率与事件的独立性", 0.8, {}),
            "MATH-PROB-04": ("离散型随机变量及其分布", 0.9, {
                "MATH-PROB-04-01": ("分布列与期望", 0.7, {}),
                "MATH-PROB-04-02": ("二项分布", 0.7, {}),
                "MATH-PROB-04-03": ("正态分布", 0.6, {}),
            }),
            "MATH-PROB-05": ("抽样方法", 0.5, {}),
            "MATH-PROB-06": ("用样本估计总体", 0.6, {}),
            "MATH-PROB-07": ("变量间的相关关系与回归分析", 0.7, {}),
            "MATH-PROB-08": ("独立性检验", 0.6, {}),
        }),
        "MATH-COUNT": ("计数原理", 0.6, {
            "MATH-COUNT-01": ("分类加法计数原理与分步乘法计数原理", 0.5, {}),
            "MATH-COUNT-02": ("排列与组合", 0.6, {
                "MATH-COUNT-02-01": ("排列", 0.5, {}),
                "MATH-COUNT-02-02": ("组合", 0.5, {}),
            }),
            "MATH-COUNT-03": ("二项式定理", 0.5, {}),
        }),
    }),
}


def build(code, name, weight, children, order):
    return {"code": code, "name": name, "description": None, "exam_weight": weight,
            "order_no": order,
            "children": [build(c, n, w, ch, i) for i, (c, (n, w, ch)) in enumerate(children.items())]}


data = {"subject": {"code": "math", "name": "高中数学", "stage": "高中"},
        "nodes": [build(c, n, w, ch, 0) for c, (n, w, ch) in TREE.items()]}
Path("data").mkdir(exist_ok=True)
Path("data/kp_math.json").write_text(
    json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
```

- [ ] **Step 2: 写种子校验测试**

`backend/tests/test_kp_seed.py`：

```python
"""S2-9 种子数据静态校验：节点数、深度、code 唯一、父链完整。"""
from __future__ import annotations

from pathlib import Path

from app.services.kp_import import flatten_tree, load_tree_file

SEED = Path(__file__).resolve().parents[1] / "data" / "kp_math.json"


def test_seed_tree_has_at_least_100_nodes() -> None:
    tree = load_tree_file(SEED)
    flat = flatten_tree(tree.nodes)
    assert len(flat) >= 100


def test_seed_tree_is_four_levels_and_codes_unique() -> None:
    tree = load_tree_file(SEED)
    flat = flatten_tree(tree.nodes)
    assert max(item.level for item in flat) == 4
    assert len({item.code for item in flat}) == len(flat)
    roots = [item for item in flat if item.parent_code is None]
    assert len(roots) == 1
    assert roots[0].code == "MATH"


def test_seed_tree_parent_codes_all_exist() -> None:
    tree = load_tree_file(SEED)
    flat = flatten_tree(tree.nodes)
    codes = {item.code for item in flat}
    assert all(item.parent_code in codes for item in flat if item.parent_code)
```

- [ ] **Step 3: 写 CLI**

`backend/scripts/import_kp_tree.py`：

```python
"""S2-9 知识点树导入 CLI：append / overwrite，支持 --dry-run。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.db import get_session_factory  # noqa: E402
from app.services.kp_import import import_tree, load_tree_file  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导入知识点树 JSON")
    parser.add_argument("--file", default="data/kp_math.json", help="种子 JSON 路径")
    parser.add_argument("--mode", choices=["append", "overwrite"], default="append")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不落库")
    args = parser.parse_args(argv)

    try:
        tree = load_tree_file(Path(args.file))
        session = get_session_factory()()
        try:
            result = import_tree(
                session, tree=tree, mode=args.mode, dry_run=args.dry_run
            )
        finally:
            session.close()
    except (FileNotFoundError, ValueError) as exc:
        print(f"数据错误: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 —— CLI 需要给出可读失败
        print(f"导入失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    prefix = "[dry-run] " if args.dry_run else ""
    stats = result.stats
    print(
        f"{prefix}导入完成 subject={tree.subject.code} mode={args.mode} "
        f"created={stats.created} updated={stats.updated} deleted={stats.deleted} "
        f"skipped={stats.skipped} unchanged={stats.unchanged}"
    )
    for code, reason in result.skipped:
        print(f"skip code={code} reason={reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行种子测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_kp_seed.py tests/test_kp_import.py -q`
Expected: `14 passed`（3 种子 + 11 导入）

- [ ] **Step 5: 提交**

```bash
git add backend/data/kp_math.json backend/scripts/import_kp_tree.py backend/app/services/kp_import.py backend/tests/test_kp_seed.py
git commit -m "feat(s2-9): 高中数学知识点种子与导入脚本"
```

---

### Task 4: 知识点接口

**Files:**
- Create: `backend/app/api/v1/kp.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/test_kp_api.py`

**Interfaces:**
- Consumes: `kp_service`、`require_role`、`get_current_user`
- Produces: 5 个 `/api/v1/kp*` 接口

- [ ] **Step 1: 写失败测试**

`backend/tests/test_kp_api.py`：

```python
"""S2-9 知识点接口：TestClient + FakeSession。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.knowledge_point import KnowledgePoint
from app.models.subject import Subject
from app.models.user import User


class FakeSession:
    def __init__(
        self,
        *,
        user: User | None = None,
        subject: Subject | None = None,
        rows: list[KnowledgePoint] | None = None,
        get_map: dict[int, KnowledgePoint] | None = None,
        duplicate: bool = False,
        has_child: bool = False,
    ) -> None:
        self.user = user
        self.subject = subject
        self.rows = rows or []
        self.get_map = get_map or {}
        self.duplicate = duplicate
        self.has_child = has_child
        self.added: list[KnowledgePoint] = []
        self.deleted: list[KnowledgePoint] = []
        self.commits = 0

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        sql = str(statement)
        if entity is User:
            return self.user
        if entity is Subject:
            return self.subject
        if "FROM note_kps" in sql or "FROM knowledge_edges" in sql:
            return None
        if entity is KnowledgePoint:
            if "parent_id" in sql:
                return 1 if self.has_child else None
            return 1 if self.duplicate else None
        raise AssertionError(f"unexpected scalar: {sql}")

    def scalars(self, statement: object):
        return list(self.rows)

    def get(self, entity: type, pk: int):
        if entity is KnowledgePoint:
            return self.get_map.get(pk)
        raise AssertionError(f"unexpected get: {entity}")

    def add(self, instance: KnowledgePoint) -> None:
        self.added.append(instance)

    def flush(self) -> None:
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = 100

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def refresh(self, instance: object) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = 100

    def delete(self, instance: KnowledgePoint) -> None:
        self.deleted.append(instance)


def _user(role: str = "teacher", user_id: int = 1) -> User:
    user = User(
        username=f"{role}_kp",
        password_hash="hash",
        nickname=f"测试用户_{user_id}",
        grade="高一",
        role=role,
    )
    user.id = user_id
    user.created_at = datetime.now(timezone.utc)
    return user


def _subject() -> Subject:
    subject = Subject(name="高中数学", code="math", stage="高中")
    subject.id = 1
    return subject


def _kp(kp_id: int, code: str, level: int, parent_id: int | None = None) -> KnowledgePoint:
    kp = KnowledgePoint(
        subject_id=1,
        parent_id=parent_id,
        name=code,
        code=code,
        level=level,
        description=None,
        exam_weight=None,
        order_no=0,
    )
    kp.id = kp_id
    return kp


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(session: FakeSession) -> None:
    app.dependency_overrides[get_db] = lambda: session


def test_list_subjects_returns_subjects(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user, subject=_subject(), rows=[_subject()]))
    resp = client.get("/api/v1/kp/subjects", headers=_headers(user))
    assert resp.status_code == 200
    assert resp.json()["data"][0]["code"] == "math"


def test_tree_returns_nested_nodes(client: TestClient) -> None:
    user = _user()
    _wire(
        FakeSession(
            user=user,
            subject=_subject(),
            rows=[_kp(1, "MATH", 1), _kp(2, "MATH-SET", 2, 1)],
        )
    )
    resp = client.get("/api/v1/kp/tree?subject=math", headers=_headers(user))
    assert resp.status_code == 200
    nodes = resp.json()["data"]["nodes"]
    assert nodes[0]["children"][0]["code"] == "MATH-SET"


def test_tree_missing_subject_param_returns_422(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    resp = client.get("/api/v1/kp/tree", headers=_headers(user))
    assert resp.status_code == 422


def test_tree_unknown_subject_returns_404(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    resp = client.get("/api/v1/kp/tree?subject=nope", headers=_headers(user))
    assert resp.status_code == 404


def test_create_kp_forbidden_for_student(client: TestClient) -> None:
    user = _user(role="student")
    _wire(FakeSession(user=user, subject=_subject()))
    resp = client.post(
        "/api/v1/kp",
        json={"subject": "math", "code": "MATH-X", "name": "X"},
        headers=_headers(user),
    )
    assert resp.status_code == 403


def test_create_kp_teacher_returns_201(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user, subject=_subject()))
    resp = client.post(
        "/api/v1/kp",
        json={"subject": "math", "code": "MATH-X", "name": "X"},
        headers=_headers(user),
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["level"] == 1


def test_create_kp_duplicate_code_returns_409(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user, subject=_subject(), duplicate=True))
    resp = client.post(
        "/api/v1/kp",
        json={"subject": "math", "code": "MATH-X", "name": "X"},
        headers=_headers(user),
    )
    assert resp.status_code == 409


def test_patch_kp_moves_and_returns_level(client: TestClient) -> None:
    user = _user()
    kp = _kp(1, "MATH-A", 1)
    parent = _kp(2, "MATH-B", 1)
    _wire(FakeSession(user=user, rows=[kp, parent], get_map={1: kp, 2: parent}))
    resp = client.patch(
        "/api/v1/kp/1", json={"parent_id": 2}, headers=_headers(user)
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["level"] == 2


def test_delete_kp_with_children_returns_409(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user, get_map={1: _kp(1, "MATH", 1)}, has_child=True))
    resp = client.delete("/api/v1/kp/1", headers=_headers(user))
    assert resp.status_code == 409


def test_delete_leaf_returns_204(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user, get_map={1: _kp(1, "MATH", 1)}))
    resp = client.delete("/api/v1/kp/1", headers=_headers(user))
    assert resp.status_code == 204
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_kp_api.py -q`
Expected: FAIL，404（路由未挂载）

- [ ] **Step 3: 实现路由**

`backend/app/api/v1/kp.py`：

```python
"""S2-9 知识点树接口（API.md §4）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.kp import KpCreate, KpNodeOut, KpTreeOut, KpUpdate, SubjectOut
from app.services import kp_service

router = APIRouter(prefix="/kp", tags=["kp"])


@router.get("/subjects", response_model=Envelope[list[SubjectOut]], summary="学科列表")
def list_subjects(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[list[SubjectOut]]:
    subjects = kp_service.list_subjects(session)
    return Envelope(
        trace_id=get_trace_id(),
        data=[SubjectOut.model_validate(subject) for subject in subjects],
    )


@router.get("/tree", response_model=Envelope[KpTreeOut], summary="知识点树")
def get_tree(
    subject: str = Query(min_length=1, max_length=30, description="学科 code"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[KpTreeOut]:
    return Envelope(trace_id=get_trace_id(), data=kp_service.get_tree(session, subject_code=subject))


@router.post("", status_code=201, response_model=Envelope[KpNodeOut], summary="新建知识点")
def create_kp(
    payload: KpCreate,
    current_user: User = Depends(require_role("admin", "teacher")),
    session: Session = Depends(get_db),
) -> Envelope[KpNodeOut]:
    kp = kp_service.create_kp(session, payload=payload)
    return Envelope(trace_id=get_trace_id(), data=KpNodeOut.model_validate(kp))


@router.patch("/{kp_id}", response_model=Envelope[KpNodeOut], summary="更新知识点")
def update_kp(
    kp_id: int,
    payload: KpUpdate,
    current_user: User = Depends(require_role("admin", "teacher")),
    session: Session = Depends(get_db),
) -> Envelope[KpNodeOut]:
    kp = kp_service.update_kp(session, kp_id=kp_id, payload=payload)
    return Envelope(trace_id=get_trace_id(), data=KpNodeOut.model_validate(kp))


@router.delete("/{kp_id}", status_code=204, summary="删除知识点")
def delete_kp(
    kp_id: int,
    current_user: User = Depends(require_role("admin", "teacher")),
    session: Session = Depends(get_db),
) -> None:
    kp_service.delete_kp(session, kp_id=kp_id)
```

`backend/app/api/router.py`：

```python
from app.api.v1 import auth, files, kp, notes, tasks

api_router.include_router(kp.router)
```

- [ ] **Step 4: 接口测试与全量**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_kp_api.py -q`
Expected: `10 passed`

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest -q`
Expected: `461 passed, 1 warning`（425 + 36）

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/v1/kp.py backend/app/api/router.py backend/tests/test_kp_api.py
git commit -m "feat(s2-9): 知识点树接口"
```

---

### Task 5: 真实导入与接口验收

**Files:** 无代码改动

- [ ] **Step 1: 导入种子**

```bash
cd backend && ../.venv/Scripts/python.exe scripts/import_kp_tree.py --file data/kp_math.json --mode append
```

Expected：`created=108 ...`；退出 0

- [ ] **Step 2: 库内核验**

```bash
docker exec study-agent-postgres psql -U study -d study_agent -c "select count(*) from subjects;"
docker exec study-agent-postgres psql -U study -d study_agent -c "select level, count(*) from knowledge_points group by level order by level;"
docker exec study-agent-postgres psql -U study -d study_agent -c "select code,name from knowledge_points where level=1;"
```

Expected：subjects=1；level 1–4 分布；level1 仅 `MATH`

- [ ] **Step 3: 幂等追加**

```bash
cd backend && ../.venv/Scripts/python.exe scripts/import_kp_tree.py --file data/kp_math.json --mode append
```

Expected：`created=0 updated=0 unchanged=108`；库内仍 108

- [ ] **Step 4: 起 uvicorn，注册 teacher 并读树**

```bash
cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 --log-level warning
# 另一终端
curl -s -X POST localhost:8000/api/v1/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"kp_teacher","password":"test-pass-123","nickname":"知识点老师","role":"teacher"}'
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"kp_teacher","password":"test-pass-123"}' | ./.venv/Scripts/python.exe -c "import sys,json;print(json.load(sys.stdin)['data']['access_token'])")
curl -s localhost:8000/api/v1/kp/subjects -H "Authorization: Bearer $TOKEN"
curl -s "localhost:8000/api/v1/kp/tree?subject=math" -H "Authorization: Bearer $TOKEN" > /tmp/kp_tree.json
./.venv/Scripts/python.exe - <<'PY'
import json
tree = json.load(open("/tmp/kp_tree.json", encoding="utf-8"))["data"]
def count(nodes): return sum(1 + count(n["children"]) for n in nodes)
print("roots", len(tree["nodes"]), "total", count(tree["nodes"]))
PY
```

Expected：subjects 含 math；roots=1、total=108

- [ ] **Step 5: 写接口与权限**

```bash
# student 写 → 403
curl -s -X POST localhost:8000/api/v1/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"kp_student","password":"test-pass-123","nickname":"知识点学生"}'
STOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"kp_student","password":"test-pass-123"}' | ./.venv/Scripts/python.exe -c "import sys,json;print(json.load(sys.stdin)['data']['access_token'])")
curl -s -w '\nHTTP=%{http_code}\n' -X POST localhost:8000/api/v1/kp -H "Authorization: Bearer $STOKEN" \
  -H 'Content-Type: application/json' -d '{"subject":"math","code":"MATH-DEMO","name":"演示"}'
# teacher 建叶子 → 201
curl -s -w '\nHTTP=%{http_code}\n' -X POST localhost:8000/api/v1/kp -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"subject":"math","parent_id":<某三级 id>,"code":"MATH-DEMO","name":"演示节点","exam_weight":0.3}'
```

Expected：student 403/40300；teacher 201 且 level=父+1

- [ ] **Step 6: PATCH 移动 / 删除保护 / 删除叶子**

```bash
curl -s -X PATCH localhost:8000/api/v1/kp/<demo_id> -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"parent_id":<另一个一级 id>}'
curl -s -w '\nHTTP=%{http_code}\n' -X DELETE localhost:8000/api/v1/kp/1 -H "Authorization: Bearer $TOKEN"
docker exec study-agent-postgres psql -U study -d study_agent -c \
 "insert into note_kps(note_id,kp_id,source,confirmed) select n.id, <demo_id>, 'manual', true from notes n limit 1;"
# 若无笔记，先插一条 notes 行再建引用
curl -s -w '\nHTTP=%{http_code}\n' -X DELETE localhost:8000/api/v1/kp/<demo_id> -H "Authorization: Bearer $TOKEN"
# 清理引用后再删 → 204
```

Expected：PATCH 200 且 `level` 更新；删根 409「存在子知识点」；被笔记引用 409「已被笔记引用」；清引用后 204

- [ ] **Step 7: overwrite 与 dry-run**

```bash
cd backend && ../.venv/Scripts/python.exe scripts/import_kp_tree.py --file data/kp_math.json --mode overwrite --dry-run
# 生成去掉一个叶子的临时文件后：
../.venv/Scripts/python.exe scripts/import_kp_tree.py --file /tmp/kp_math_minus_one.json --mode overwrite
```

Expected：dry-run 打印 `created=0 updated=0 deleted=0 ...`；正式 overwrite 打印 `deleted=1` 且该 code 从库消失；被引用节点若在删除集内打印 `skip ... reason=referenced`

- [ ] **Step 8: 清理与全量测试**

```bash
docker exec study-agent-postgres psql -U study -d study_agent -c \
 "delete from note_kps; delete from notes; delete from knowledge_edges; delete from knowledge_points; delete from subjects; delete from users where username like 'kp\\_%';"
cd backend && ../.venv/Scripts/python.exe -m pytest -q
```

Expected：表清空；`461 passed, 1 warning`

---

### Task 6: 文档同步与提交

**Files:** `docs/API.md`、`docs/SCHEMA.md`、`AGENTS.md`、`docs/DECISIONS.md`、`docs/PROGRESS.md`、`docs/AI协作开发实施计划.md`、spec/plan

- [ ] **Step 1: API.md §4**

补全 5 个接口的权限、入参、出参、错误码；`GET /kp/tree` 权限由 student 改为“登录用户”。

- [ ] **Step 2: SCHEMA.md §3.1**

注记：S2-9 起由导入脚本写入；`level` 由父节点推导；删除由业务保护（无级联）；`code` 稳定不可改。

- [ ] **Step 3: AGENTS.md**

§9.2 加：树查询一次查完内存组树；level 只由父推导；删除保护顺序；导入 append/overwrite 语义。§9.6 加 `kp_service`/`kp_import` 锚点。

- [ ] **Step 4: DECISIONS D-029**

记录 14 条决策、验证数字、种子数据人工校对要求、已知限制。

- [ ] **Step 5: PROGRESS 与实施计划**

状态改 S2-9 完成、下一步 S2-10；勾选 `[x] S2-9`；遗留补导入并发/无拖拽/权重经验值；追加 2026-10-26（S2-9）日志。

- [ ] **Step 6: spec/plan 执行记录**

spec 状态改已验收；plan 填 commit 列表、pytest 数字、真实导入/接口证据、偏差。

- [ ] **Step 7: 提交**

```bash
git add docs/ AGENTS.md
git commit -m "docs(s2-9): 知识点树契约、决策与进度同步"
```

---

## Self-Review

- 覆盖 spec：读/写接口（Task 4）、树查询与校验（Task 1）、导入模式与引用保护（Task 2）、种子与 CLI（Task 3）、真实验收（Task 5）、文档（Task 6）。
- 类型一致：`KpCreate/KpUpdate`、`flat.parent_code`、`SyncPlan.skipped`、`ImportResult.stats/skipped` 在各 task 间一致。
- 测试数：12 + 11 + 3 + 10 = 36（较 spec 的 32 多 4：种子 3 + has_children 1）→ 全量 425 + 36 = 461。

> 执行时以实际 pytest 输出为准回填数字。