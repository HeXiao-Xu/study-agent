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
    target = _kp(1, "MATH-C", 3, None)
    moving = _kp(2, "MATH-B", 2, None)
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

def test_reorder_children_updates_sibling_order() -> None:
    root = _kp(1, "MATH", 1, None)
    first = _kp(2, "MATH-A", 2, 1, order_no=0)
    second = _kp(3, "MATH-B", 2, 1, order_no=1)
    third = _kp(4, "MATH-C", 2, 1, order_no=2)
    session = FakeSession(rows=[root, first, second, third], get_map={1: root})

    kp_service.reorder_children(
        session,  # type: ignore[arg-type]
        parent_id=1,
        ordered_ids=[4, 2, 3],
    )

    assert [first.order_no, second.order_no, third.order_no] == [1, 2, 0]
    assert session.commits == 1


def test_reorder_children_moves_subtree_and_recalculates_levels() -> None:
    root = _kp(1, "MATH", 1, None)
    target = _kp(2, "MATH-FUNC", 2, 1)
    moving = _kp(3, "MATH-GEO", 1, None, order_no=1)
    child = _kp(4, "MATH-GEO-01", 2, 3)
    sibling = _kp(5, "MATH-FUNC-01", 3, 2)
    session = FakeSession(
        rows=[root, target, moving, child, sibling],
        get_map={2: target},
    )

    kp_service.reorder_children(
        session,  # type: ignore[arg-type]
        parent_id=2,
        ordered_ids=[5, 3],
        moved_id=3,
    )

    assert moving.parent_id == 2
    assert moving.level == 3
    assert child.level == 4
    assert sibling.order_no == 0
    assert moving.order_no == 1
    assert root.order_no == 0
    assert session.commits == 1


def test_reorder_children_rejects_duplicate_ids() -> None:
    with pytest.raises(InvalidParamError, match="不能重复"):
        kp_service.reorder_children(
            FakeSession(),  # type: ignore[arg-type]
            parent_id=None,
            ordered_ids=[1, 1],
        )


def test_reorder_children_rejects_incomplete_sibling_set() -> None:
    root = _kp(1, "MATH", 1, None)
    first = _kp(2, "MATH-A", 2, 1)
    second = _kp(3, "MATH-B", 2, 1)
    session = FakeSession(rows=[root, first, second], get_map={1: root})

    with pytest.raises(InvalidParamError, match="全部子节点"):
        kp_service.reorder_children(
            session,  # type: ignore[arg-type]
            parent_id=1,
            ordered_ids=[2],
        )


def test_reorder_children_rejects_cycle() -> None:
    root = _kp(1, "MATH", 1, None)
    parent = _kp(2, "MATH-A", 2, 1)
    child = _kp(3, "MATH-A-01", 3, 2)
    session = FakeSession(rows=[root, parent, child], get_map={3: child})

    with pytest.raises(InvalidParamError, match="子节点"):
        kp_service.reorder_children(
            session,  # type: ignore[arg-type]
            parent_id=3,
            ordered_ids=[2],
            moved_id=2,
        )


def test_reorder_children_rejects_missing_parent() -> None:
    with pytest.raises(NotFoundError, match="父节点不存在"):
        kp_service.reorder_children(
            FakeSession(),  # type: ignore[arg-type]
            parent_id=99,
            ordered_ids=[1],
        )
