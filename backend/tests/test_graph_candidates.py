"""S4-5 候选构造纯函数：路径、前置候选、相似度分档、方向守卫。"""
from __future__ import annotations

from app.ai.graph.candidates import (
    KpBrief,
    Pair,
    build_paths,
    direction_conflicts,
    pair_candidates,
    prereq_candidates,
)


def _kp(
    kp_id: int, name: str, level: int, parent_id: int | None, vec: list[float] | None = None
) -> KpBrief:
    return KpBrief(
        kp_id=kp_id, name=name, level=level, parent_id=parent_id, embedding=vec, path=""
    )


def test_build_paths_joins_ancestors():
    nodes = [_kp(1, "函数", 1, None), _kp(2, "单调性", 2, 1), _kp(3, "比较大小", 3, 2)]
    assert build_paths(nodes) == {1: "函数", 2: "函数 / 单调性", 3: "函数 / 单调性 / 比较大小"}


def test_build_paths_survives_cycle():
    nodes = [_kp(1, "甲", 2, 2), _kp(2, "乙", 2, 1)]
    paths = build_paths(nodes)
    assert paths[1] and paths[2]
    assert len(paths[1].split(" / ")) <= 10


def test_prereq_candidates_sorted_by_cosine_and_excludes_parent():
    target = _kp(10, "导数应用", 3, 2, [1.0, 0.0])
    nodes = [
        target,
        _kp(2, "单调性", 2, 1, [0.9, 0.1]),
        _kp(11, "极值", 3, 2, [0.1, 1.0]),
        _kp(12, "向量", 3, 5, [0.0, 1.0]),
        _kp(13, "无关", 3, 6, [-1.0, 0.0]),
    ]
    picked = prereq_candidates(target, nodes, build_paths(nodes), top_k=2, exclude_ids={2})
    assert [item.kp_id for item in picked] == [11, 12]
    assert picked[0].cos > picked[1].cos


def test_prereq_candidates_skip_nodes_without_embedding():
    target = _kp(10, "导数应用", 3, 2, [1.0, 0.0])
    nodes = [target, _kp(11, "极值", 3, 2, None)]
    assert prereq_candidates(target, nodes, build_paths(nodes)) == []


def test_prereq_candidates_empty_when_target_has_no_embedding():
    target = _kp(10, "导数应用", 3, 2, None)
    nodes = [target, _kp(11, "极值", 3, 2, [1.0, 0.0])]
    assert prereq_candidates(target, nodes, build_paths(nodes)) == []


def test_pair_candidates_buckets_by_threshold():
    # 余弦 0.96 → confusable；0.80 → related；0.50 → 丢弃
    a = _kp(1, "A", 3, 100, [1.0, 0.0])
    b = _kp(2, "B", 3, 200, [0.96, 0.28])
    c = _kp(3, "C", 3, 300, [0.80, 0.60])
    d = _kp(4, "D", 3, 400, [0.50, 0.866])
    related, confusable = pair_candidates([a, b, c, d])
    assert Pair(1, 3, related[0].cos) in related
    assert all(pair.src_kp_id < pair.dst_kp_id for pair in [*related, *confusable])
    assert (1, 2) not in {(p.src_kp_id, p.dst_kp_id) for p in related}
    assert (1, 2) in {(p.src_kp_id, p.dst_kp_id) for p in confusable}


def test_pair_candidates_same_parent_uses_lower_threshold():
    a = _kp(1, "A", 3, 100, [1.0, 0.0])
    b = _kp(2, "B", 3, 100, [0.80, 0.60])
    _, confusable = pair_candidates([a, b])
    assert (1, 2) in {(p.src_kp_id, p.dst_kp_id) for p in confusable}


def test_pair_candidates_skip_same_parent_for_related():
    a = _kp(1, "A", 3, 100, [1.0, 0.0])
    b = _kp(2, "B", 3, 100, [0.80, 0.60])
    related, _ = pair_candidates([a, b])
    assert related == []


def test_pair_candidates_never_duplicates_a_pair():
    a = _kp(1, "A", 3, 100, [1.0, 0.0])
    b = _kp(2, "B", 3, 200, [1.0, 0.0])
    _, confusable = pair_candidates([a, b])
    keys = [(pair.src_kp_id, pair.dst_kp_id) for pair in confusable]
    assert keys == [(1, 2)]


def test_direction_conflicts_flags_reverse_edge():
    existing = [(5, 6, "prerequisite"), (9, 8, "related")]
    assert direction_conflicts(existing) == {(5, 6)}


def test_prereq_candidates_excludes_same_name_nodes():
    """不同章节的同名节点余弦≈1，但只能算易混，不能当前置。"""
    target = KpBrief(kp_id=1, name="定义与标准方程", level=3, parent_id=2, embedding=[1.0, 0.0])
    other = KpBrief(kp_id=9, name="定义与标准方程", level=3, parent_id=8, embedding=[1.0, 0.0])
    plain = KpBrief(kp_id=5, name="直线的方程", level=3, parent_id=3, embedding=[0.9, 0.1])
    candidates = prereq_candidates(target, [target, other, plain], {1: "椭圆/定义", 9: "双曲线/定义", 5: "直线/方程"})
    assert [item.kp_id for item in candidates] == [5]


def test_pair_candidates_skips_ancestor_descendant_pairs():
    """上下级关系由 contains 表达，不能再进「相关/易混」，否则人工审核全是噪音。"""
    nodes = [
        KpBrief(kp_id=1, name="解析几何", level=2, parent_id=None, embedding=[1.0, 0.0]),
        KpBrief(kp_id=2, name="椭圆", level=3, parent_id=1, embedding=[0.98, 0.02]),
        KpBrief(kp_id=3, name="双曲线", level=3, parent_id=1, embedding=[0.97, 0.03]),
    ]
    related, confusable = pair_candidates(nodes, top_k=8, confusable_lo=0.95)
    keys = {(p.src_kp_id, p.dst_kp_id) for p in related + confusable}
    assert (1, 2) not in keys and (1, 3) not in keys
    assert (2, 3) in keys  # 同父兄弟仍保留
