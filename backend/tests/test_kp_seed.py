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