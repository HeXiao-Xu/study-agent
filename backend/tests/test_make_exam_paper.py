"""S4-1 验收卷的数据结构：20 题、题号连续、每题有答案。

这是自编卷（非真题），测试只保证结构与文档一致，不保证题目难度分布。
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from make_s4_1_exam_paper import QUESTIONS  # noqa: E402


def test_twenty_questions_with_continuous_numbers() -> None:
    assert [item["no"] for item in QUESTIONS] == list(range(1, 21))


def test_section_split_8_4_8() -> None:
    choice = [item for item in QUESTIONS if item.get("options")]
    blank = [item for item in QUESTIONS if not item.get("options") and item["no"] <= 12]
    solution = [item for item in QUESTIONS if not item.get("options") and item["no"] > 12]
    assert (len(choice), len(blank), len(solution)) == (8, 4, 8)


def test_every_question_has_answer_and_analysis() -> None:
    for item in QUESTIONS:
        assert item["answer"].strip(), item["no"]
        assert item["analysis"].strip(), item["no"]


def test_stems_do_not_start_with_digit() -> None:
    """题号由渲染器加，题干自带数字会让切题器把题干当新题。"""
    for item in QUESTIONS:
        assert not item["stem"].lstrip()[:1].isdigit(), item["no"]