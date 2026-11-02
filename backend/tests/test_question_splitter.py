"""S4-1 切题规则：边界正确性直接决定题库质量，规则全部在这里钉死。"""
from __future__ import annotations

from app.ai.extract.splitter import split_questions


def paper(*lines: str) -> str:
    return "\n".join(lines)


def test_splits_three_number_styles() -> None:
    text = paper("一、选择题（本题共 3 小题）", "1. 甲题", "A. 1 B. 2", "2、乙题", "3．丙题")
    result = split_questions(text)
    assert [block.index for block in result.blocks] == [1, 2, 3]
    assert result.blocks[1].text.startswith("2、乙题")
    assert result.blocks[2].section_qtype == "单选"
    assert result.expected_count == 3
    assert result.degraded is False


def test_decimal_line_does_not_split() -> None:
    text = paper("三、解答题（本题共 1 小题）", "1. 解方程：", "1.5 是解吗？")
    result = split_questions(text)
    assert result.detected_count == 1
    assert "1.5 是解吗？" in result.blocks[0].text


def test_sub_questions_are_kept_inside_block() -> None:
    text = paper("三、解答题（本题共 1 小题）", "1. 已知 f(x)=x²。", "（1）求 f(1)；", "（2）求 f(2)。")
    result = split_questions(text)
    assert result.detected_count == 1
    assert "（2）求 f(2)。" in result.blocks[0].text


def test_paren_numbering_is_not_a_question_start() -> None:
    text = paper("三、解答题（本题共 1 小题）", "1. 求证：", "1) 先证充分性", "2) 再证必要性")
    result = split_questions(text)
    assert result.detected_count == 1


def test_section_headers_carry_qtype_and_count() -> None:
    text = paper(
        "一、选择题（本题共 2 小题，每小题 5 分）",
        "1. 甲乙",
        "2. 丙丁",
        "二、填空题（本题共 1 小题）",
        "3. 填空甲",
    )
    result = split_questions(text)
    assert result.expected_count == 3
    assert result.blocks[0].section_qtype == "单选"
    assert result.blocks[2].section_qtype == "填空"
    assert result.blocks[2].section_index == 1
    assert result.degraded is False


def test_expected_count_sums_sections() -> None:
    text = paper(
        "一、选择题（本题共 8 小题）",
        *[f"{i}. 选择{i}" for i in range(1, 9)],
        "二、填空题（本题共 4 小题）",
        *[f"{i}. 填空{i}" for i in range(9, 13)],
    )
    result = split_questions(text)
    assert result.expected_count == 12
    assert result.detected_count == 12
    assert result.degraded is False


def test_number_gap_warns_but_keeps_block() -> None:
    text = paper("一、选择题（本题共 3 小题）", "1. 甲", "2. 乙", "4. 丁")
    result = split_questions(text)
    assert result.detected_count == 3
    assert "4. 丁" in result.blocks[2].text
    assert any("跳号" in warning for warning in result.warnings)
    assert result.degraded is False


def test_preamble_headers_never_reach_stem() -> None:
    text = paper(
        "某市第二中学 2026 学年度期末试卷",
        "姓名：______ 班级：______ 考号：______",
        "一、选择题（本题共 1 小题）",
        "1. 甲题",
    )
    result = split_questions(text)
    assert "姓名" not in result.blocks[0].text
    assert result.blocks[0].text.startswith("1. 甲题")


def test_school_name_inside_stem_is_kept() -> None:
    text = paper(
        "三、解答题（本题共 1 小题）",
        "1. 某中学组织研学，已知参加人数为 200，求比例。",
    )
    assert "某中学" in split_questions(text).blocks[0].text


def test_footer_between_questions_is_stripped() -> None:
    text = paper(
        "一、选择题（本题共 2 小题）",
        "1. 甲题",
        "第 1 页 共 4 页",
        "2. 乙题",
    )
    result = split_questions(text)
    assert result.detected_count == 2
    assert "第 1 页" not in result.blocks[0].text
    assert "第 1 页" not in result.blocks[1].text


def test_no_question_number_degrades() -> None:
    result = split_questions(paper("这是一段没有题号的文本。", "第二段。"))
    assert result.blocks == []
    assert result.degraded is True


def test_count_mismatch_degrades() -> None:
    text = paper("一、选择题（本题共 5 小题）", "1. 甲", "2. 乙", "3. 丙", "4. 丁")
    result = split_questions(text)
    assert result.detected_count == 4
    assert result.degraded is True
    assert any("声明" in warning for warning in result.warnings)


def test_empty_text_degrades() -> None:
    result = split_questions("   ")
    assert result.blocks == []
    assert result.degraded is True


def test_two_digit_numbers_are_single_questions() -> None:
    text = paper(
        "一、选择题（本题共 11 小题）",
        *[f"{index}. 第{index}题" for index in range(1, 12)],
    )
    result = split_questions(text)
    assert result.detected_count == 11
    assert result.blocks[9].text.startswith("10. 第10题")


def test_partial_declared_counts_disable_expected_total() -> None:
    text = paper(
        "一、选择题（本题共 8 小题）",
        *[f"{i}. 选择{i}" for i in range(1, 9)],
        "二、填空题（本题共 4 小题）",
        *[f"{i}. 填空{i}" for i in range(9, 13)],
        "三、解答题",
        *[f"{i}. 解答{i}" for i in range(13, 21)],
    )
    result = split_questions(text)
    assert result.detected_count == 20
    assert result.expected_count is None
    assert result.degraded is False


def test_all_sections_declared_sums_to_total() -> None:
    text = paper(
        "一、选择题（本题共 8 小题）",
        *[f"{i}. 选择{i}" for i in range(1, 9)],
        "二、填空题（本题共 4 小题）",
        *[f"{i}. 填空{i}" for i in range(9, 13)],
        "三、解答题（本题共 8 小题）",
        *[f"{i}. 解答{i}" for i in range(13, 21)],
    )
    result = split_questions(text)
    assert result.detected_count == 20
    assert result.expected_count == 20
    assert result.degraded is False