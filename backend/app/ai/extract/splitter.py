"""S4-1 试卷切题：纯函数，无 IO / DB / LLM。

边界为什么用规则而不是让 LLM 直接切：LLM 整卷输出会漏题、串题，
且一次失败就要重跑整卷。规则先给出确定的题号边界，LLM 只负责单题结构化；
规则失手时才退化成整卷一遍（degraded=True 显式暴露）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 大题标题：「一、选择题」；也认「二. 填空题」
SECTION_RE = re.compile(r"^\s*[一二三四五六七八九十]+\s*[、.．]\s*(选择题|多选题|填空题|解答题|判断题|计算题|证明题)")
# 声明题数：「共 8 小题」；兼容「(共8小题)」
COUNT_RE = re.compile(r"(\d+)\s*小题")
# 主题号：行首的 1. / 1、/ 1．（后面必须跟非空白，避免把「3.」空行当题干）
QNUM_RE = re.compile(r"^\s*(\d{1,2})\s*[.．、]\s*\S")
# 小问编号：（1） (1) 1) ①~⑩ —— 一律不切
SUBQ_RE = re.compile(r"^\s*(?:[（(]\s*\d+\s*[）)]|\d+\s*[）)]|[①②③④⑤⑥⑦⑧⑨⑩])")
# 页脚/答题卡：可能出现在任意两题之间，全局剔除
FOOTER_RE = re.compile(r"第\s*\d+\s*页|共\s*\d+\s*页|答题卡")

_QTYPE_HINTS = {
    "选择题": "单选",
    "多选题": "多选",
    "填空题": "填空",
    "解答题": "解答",
    "判断题": "解答",
    "计算题": "解答",
    "证明题": "解答",
}


@dataclass(frozen=True)
class QuestionBlock:
    index: int
    text: str
    section_qtype: str | None
    section_index: int


@dataclass(frozen=True)
class SplitResult:
    blocks: list[QuestionBlock] = field(default_factory=list)
    detected_count: int = 0
    expected_count: int | None = None
    degraded: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Section:
    qtype: str | None
    declared: int | None
    lines: list[str]


def split_questions(text: str) -> SplitResult:
    lines = [line.rstrip() for line in (text or "").splitlines()]
    if not any(line.strip() for line in lines):
        return SplitResult(degraded=True, warnings=["文本为空，无法切题"])

    sections = _sections(lines)
    # 只有一个大题少写题数时，部分求和的 expected_count 会偏小并把整卷误判成 degraded，
    # 所以只有全部大题都声明了题数，总数才可比。
    declared_all = [section.declared for section in sections]
    expected_count = (
        sum(declared_all) if all(value is not None for value in declared_all) else None
    )

    blocks: list[QuestionBlock] = []
    warnings: list[str] = []
    for section_index, section in enumerate(sections):
        blocks.extend(
            _split_section(
                section,
                offset=len(blocks),
                section_index=section_index,
                warnings=warnings,
            )
        )

    degraded = False
    if expected_count is not None and len(blocks) != expected_count:
        degraded = True
        warnings.append(f"切出 {len(blocks)} 题，卷面声明 {expected_count} 题")
    if expected_count is None and len(sections) <= 1 and len(blocks) < 3:
        degraded = True
    return SplitResult(
        blocks=blocks,
        detected_count=len(blocks),
        expected_count=expected_count,
        degraded=degraded,
        warnings=warnings,
    )


def _sections(lines: list[str]) -> list[_Section]:
    """按大题标题切段；无大题标题时全文当一段（qtype/declared 为 None）。"""
    if not any(SECTION_RE.match(line) for line in lines):
        return [_Section(qtype=None, declared=None, lines=lines)]

    sections: list[_Section] = []
    qtype: str | None = None
    declared: int | None = None
    body: list[str] = []
    started = False
    for line in lines:
        match = SECTION_RE.match(line)
        if match:
            sections.append(_Section(qtype=qtype, declared=declared, lines=body))
            count = COUNT_RE.search(line)
            qtype = _QTYPE_HINTS.get(match.group(1))
            declared = int(count.group(1)) if count else None
            body = []
            started = True
            continue
        if not started:
            continue  # 首个大题标题之前是卷头，直接丢弃
        body.append(line)
    sections.append(_Section(qtype=qtype, declared=declared, lines=body))
    return [section for section in sections if section.lines]


def _split_section(
    section: _Section,
    *,
    offset: int,
    section_index: int,
    warnings: list[str],
) -> list[QuestionBlock]:
    blocks: list[QuestionBlock] = []
    current: list[str] | None = None
    current_no: int | None = None
    for line in section.lines:
        if FOOTER_RE.search(line):
            continue
        number = _question_number(line)
        if number is not None and _starts_question(number, current_no, section.declared, len(blocks)):
            if current is not None:
                blocks.append(_block(current, offset + len(blocks) + 1, section, section_index))
            if current_no is not None and number != current_no + 1:
                warnings.append(f"题号跳号：{current_no} → {number}")
            current, current_no = [line], number
            continue
        if current is not None:
            current.append(line)
        # current 为 None 说明还在首题号之前，属于引言/说明，丢弃
    if current is not None:
        blocks.append(_block(current, offset + len(blocks) + 1, section, section_index))
    return blocks


def _block(lines: list[str], index: int, section: _Section, section_index: int) -> QuestionBlock:
    return QuestionBlock(
        index=index,
        text="\n".join(lines).strip(),
        section_qtype=section.qtype,
        section_index=section_index,
    )


def _question_number(line: str) -> int | None:
    if SUBQ_RE.match(line):
        return None
    match = QNUM_RE.match(line)
    return int(match.group(1)) if match else None


def _starts_question(
    number: int, current_no: int | None, declared: int | None, found: int
) -> bool:
    """新题判定：题号必须递增；有声明题数时切够就停（防解答题内部的列表编号）。"""
    if current_no is None:
        return True
    if number <= current_no:
        return False
    if declared is not None:
        return found < declared
    return number == current_no + 1