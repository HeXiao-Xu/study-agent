"""生成 S4-1 验收用的 20 题高中数学卷（本人自编，非真实考试卷）。

为什么用纯文本 + Unicode 上下标而不是 Word 公式对象：`DocxParser` 抽的是纯文本，
OMML 公式会抽成空串；用 x²、√3 这类写法既能被抽出，也能被 KaTeX 正确渲染。

数据来源声明（AGENTS.md §6）：本卷题目均为本人自编的验收样例，不是任何真题或
模拟卷，卷面首页与 docstring 均如实标注，不得作为真实考试卷使用。
"""
from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.shared import Pt

DEFAULT_TARGET = (
    Path(__file__).resolve().parents[2] / "测试数据" / "高中数学试卷-高二期末综合卷（20题）.docx"
)

QUESTIONS: list[dict] = [
    {"no": 1, "stem": "已知集合 A={1,2,3}，B={2,3,4}，则 A∩B=（ ）",
     "options": ["A. {1}", "B. {2,3}", "C. {1,4}", "D. {1,2,3,4}"],
     "answer": "B", "analysis": "交集取两集合的公共元素，即 2 与 3。"},
    {"no": 2, "stem": "函数 f(x)=x²-4x+3 的最小值是（ ）",
     "options": ["A. -1", "B. 0", "C. 1", "D. 3"],
     "answer": "A", "analysis": "f(x)=(x-2)²-1，故最小值为 -1。"},
    {"no": 3, "stem": "等差数列 {aₙ} 中 a₁=2，公差 d=3，则 a₅=（ ）",
     "options": ["A. 11", "B. 12", "C. 14", "D. 17"],
     "answer": "C", "analysis": "a₅=a₁+4d=2+12=14。"},
    {"no": 4, "stem": "已知 sinα=3/5，且 α 为第一象限角，则 cosα=（ ）",
     "options": ["A. 4/5", "B. -4/5", "C. 3/4", "D. -3/4"],
     "answer": "A", "analysis": "第一象限余弦为正，cosα=√(1-9/25)=4/5。"},
    {"no": 5, "stem": "不等式 x²-5x+6<0 的解集是（ ）",
     "options": ["A. (2,3)", "B. (-∞,2)∪(3,+∞)", "C. (1,6)", "D. 空集"],
     "answer": "A", "analysis": "x²-5x+6=(x-2)(x-3)<0，解为 2<x<3。"},
    {"no": 6, "stem": "函数 f(x)=log₂(x-1) 的定义域是（ ）",
     "options": ["A. (0,+∞)", "B. (1,+∞)", "C. [1,+∞)", "D. 全体实数"],
     "answer": "B", "analysis": "真数 x-1>0，即 x>1。"},
    {"no": 7, "stem": "已知向量 a=(1,2)，b=(x,4)，且 a∥b，则 x=（ ）",
     "options": ["A. 1", "B. 2", "C. 4", "D. 8"],
     "answer": "B", "analysis": "平行则 1×4-2×x=0，得 x=2。"},
    {"no": 8, "stem": "从 5 名同学中选 2 人参加比赛，不同的选法有（ ）",
     "options": ["A. 5 种", "B. 10 种", "C. 20 种", "D. 25 种"],
     "answer": "B", "analysis": "C(5,2)=10。"},
    {"no": 9, "stem": "已知等比数列 {aₙ} 中 a₁=1，公比 q=2，则 a₄= ______。",
     "options": None, "answer": "8", "analysis": "a₄=a₁q³=1×2³=8。"},
    {"no": 10, "stem": "若 f(x)=x³-3x，则 f'(1)= ______。",
     "options": None, "answer": "0", "analysis": "f'(x)=3x²-3，f'(1)=0。"},
    {"no": 11, "stem": "圆 x²+y²-2x=0 的圆心坐标是 ______。",
     "options": None, "answer": "(1,0)", "analysis": "配方得 (x-1)²+y²=1，圆心 (1,0)。"},
    {"no": 12, "stem": "已知 tanα=2，则 sin2α= ______。",
     "options": None, "answer": "4/5", "analysis": "sin2α=2tanα/(1+tan²α)=4/5。"},
    {"no": 13, "stem": "已知函数 f(x)=x²-2x+3。（1）求 f(x) 图象的对称轴；（2）求 f(x) 在区间 [0,3] 上的最大值与最小值。",
     "options": None, "answer": "对称轴 x=1；最小值 2，最大值 6",
     "analysis": "f(x)=(x-1)²+2，对称轴 x=1；区间 [0,3] 上 f(1)=2 最小，f(3)=6 最大。"},
    {"no": 14, "stem": "已知等差数列 {aₙ} 中 a₂=5，a₆=17。（1）求通项公式；（2）求前 10 项和 S₁₀。",
     "options": None, "answer": "aₙ=3n-1；S₁₀=155",
     "analysis": "4d=12 得 d=3，a₁=2，aₙ=3n-1；S₁₀=10×2+45×3=155。"},
    {"no": 15, "stem": "已知 sinα=4/5，α∈(π/2, π)，求 sin(α+π/6) 的值。",
     "options": None, "answer": "(4√3-3)/10",
     "analysis": "cosα=-3/5；sin(α+π/6)=sinαcos(π/6)+cosαsin(π/6)=(4√3-3)/10。"},
    {"no": 16, "stem": "已知函数 f(x)=x³-3x²+2。（1）求 f'(x)；（2）求 f(x) 的极值。",
     "options": None, "answer": "f'(x)=3x²-6x；极大值 2，极小值 -2",
     "analysis": "f'(x)=3x(x-2)，x=0 处极大值 f(0)=2，x=2 处极小值 f(2)=-2。"},
    {"no": 17, "stem": "已知直线 l: y=x+1 与圆 C: x²+y²=4 相交于 A、B 两点，求弦长 |AB|。",
     "options": None, "answer": "√14",
     "analysis": "圆心到直线距离 d=1/√2，|AB|=2√(4-1/2)=√14。"},
    {"no": 18, "stem": "某校高一年级共有 300 人，用分层抽样抽取 30 人，其中男生 18 人，估计该校高一男生人数。",
     "options": None, "answer": "180 人",
     "analysis": "抽样比 30/300=1/10，男生 18÷(1/10)=180。"},
    {"no": 19, "stem": "数列 {aₙ} 满足 a₁=1，aₙ₊₁=2aₙ+1。（1）求证 {aₙ+1} 是等比数列；（2）求 aₙ。",
     "options": None, "answer": "aₙ+1=2ⁿ，即 aₙ=2ⁿ-1",
     "analysis": "(aₙ₊₁+1)/(aₙ+1)=2，首项 2，故 aₙ+1=2ⁿ。"},
    {"no": 20, "stem": "已知函数 f(x)=ln x-x+1。（1）求 f(x) 的单调区间；（2）证明 f(x)≤0。",
     "options": None, "answer": "增区间 (0,1)，减区间 (1,+∞)；最大值 f(1)=0，故 f(x)≤0",
     "analysis": "f'(x)=1/x-1=(1-x)/x，x=1 处取最大值 0。"},
]

_SECTIONS = (
    ("一、选择题（本题共 8 小题，每小题 5 分，共 40 分）", 0, 8),
    ("二、填空题（本题共 4 小题，每小题 5 分，共 20 分）", 8, 12),
    ("三、解答题（本题共 8 小题，共 90 分。解答应写出文字说明、证明过程或演算步骤）", 12, 20),
)


def _write_question(document: Document, item: dict) -> None:
    document.add_paragraph(f"{item['no']}. {item['stem']}")
    if item.get("options"):
        document.add_paragraph("    ".join(item["options"]))
    document.add_paragraph(f"【答案】{item['answer']}　【解析】{item['analysis']}")


def build_document() -> Document:
    document = Document()
    title = document.add_paragraph("高二数学期末综合卷（自编 20 题）")
    title.runs[0].font.size = Pt(16)
    document.add_paragraph("说明：本卷为毕业设计验收自编卷，非真实考试卷；答案与解析随题给出。")
    for heading, start, end in _SECTIONS:
        document.add_paragraph(heading)
        for item in QUESTIONS[start:end]:
            _write_question(document, item)
    return document


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else DEFAULT_TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    build_document().save(target)
    print(f"已生成 {len(QUESTIONS)} 题：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))