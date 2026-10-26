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
    path = _write(
        tmp_path,
        {"subject": {"code": "math", "name": "高中数学"}, "nodes": [{"name": "缺 code"}]},
    )
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
    assert [row.code for row in plan.deletes] == []
    assert ("MATH-A", "has_children") in plan.skipped