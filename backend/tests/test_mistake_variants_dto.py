"""S4-4 详情 DTO：JSONB → similar_questions / variants_stats 的映射与向前兼容。"""
from __future__ import annotations

from app.services.mistake_service import _variants_of

PAYLOAD = {
    "version": 1,
    "generated_at": "2026-11-03T14:02:11+00:00",
    "model": "qwen-plus",
    "prompt_version": "question_gen_v1",
    "stats": {"requested": 3, "passed": 2, "rejected": 1, "rounds": 2},
    "items": [
        {
            "variant_id": "abc12345",
            "stem_md": "求 $2+2$ 的值。",
            "options": None,
            "answer_md": "$4$",
            "analysis_md": "直接相加。",
            "qtype": "解答",
            "difficulty": 2,
            "kp_ids": [12],
            "self_check": {"status": "passed", "attempts": 1},
            "accepted_question_id": None,
            "accepted_at": None,
        }
    ],
    "rejected": [],
}


def test_variants_of_maps_items_and_stats():
    items, stats = _variants_of(PAYLOAD)

    assert items is not None and items[0].variant_id == "abc12345"
    assert items[0].difficulty == 2
    assert items[0].analysis_md == "直接相加。"
    assert stats is not None
    assert (stats.requested, stats.passed, stats.rejected, stats.rounds) == (3, 2, 1, 2)


def test_variants_of_returns_none_for_unknown_version():
    assert _variants_of({**PAYLOAD, "version": 2}) == (None, None)
    assert _variants_of(None) == (None, None)
    assert _variants_of({}) == (None, None)


def test_variants_of_skips_malformed_items():
    broken = {**PAYLOAD, "items": [{"variant_id": "x"}]}  # 缺 stem/answer

    items, _stats = _variants_of(broken)

    assert items == []


def test_variants_of_distinguishes_empty_items_from_null():
    empty = {**PAYLOAD, "items": [], "stats": {"requested": 3, "passed": 0, "rejected": 3, "rounds": 3}}

    items, stats = _variants_of(empty)

    assert items == []  # 已生成但全部被拦：空数组
    assert stats is not None and stats.passed == 0 and stats.rejected == 3