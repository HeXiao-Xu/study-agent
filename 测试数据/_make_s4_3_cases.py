"""S4-3 真机验收自测集：造 30 道题 + 30 条「错题 + 学生作答」，覆盖 6 类错因。

注意：这是**人工构造的自测集**，不是真实学生数据（AGENTS §6 / spec D-15）。
标签是作者按「预期最合理的错因」预先标注的，验收时按它算主因命中率。

用法（服务与 worker 已起）：
    cd backend
    ..\\.venv\\Scripts\\python.exe ..\\测试数据\\_make_s4_3_cases.py
重跑安全：题目判重命中 409 时按题干回查既有题；错题按 (user, question) 复用。
"""
from __future__ import annotations

import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8031/api/v1"
SUBJECT_ID = 7  # 高中数学
USER, PWD = "s43_accept_20261103", "accept-pass-2026"
OUT_PATH = Path(__file__).with_name("s4_3_cases.json")

# (题干, 选项, 标答, 学生作答, 人工标注错因)
# 标注口径与 `backend/app/ai/prompts/mistake_analyze_v2.md` 的「错因判定口径」一致：
#   截断 → 时间不足；读题/所求看错 → 审题偏差；公式内容记错 → 知识遗忘；
#   公式对但理解错 → 概念不清；路径/论证方法错 → 方法不当；纯数值错 → 计算失误。
CASES: list[dict] = [
    # —— 概念不清 ×5（公式/概念理解错，不是记错）——
    {"stem": "已知函数 $f(x)=x^2-4x+3$，求其对称轴。", "options": None,
     "answer": "$x=2$", "my_answer": "对称轴就是顶点，顶点是 $(2,-1)$，所以对称轴是 $(2,-1)$",
     "label": "概念不清"},
    {"stem": "求函数 $y=2x^2+4x-1$ 的最小值。", "options": None,
     "answer": "$-3$", "my_answer": "因为 $a=2>0$ 开口向上，最小值就是常数项，最小值是 -1",
     "label": "概念不清"},
    {"stem": "判断函数 $f(x)=\\frac{1}{x}$ 在 $(0,+\\infty)$ 上的单调性。", "options": None,
     "answer": "单调递减", "my_answer": "x 越大 $\\frac{1}{x}$ 越大，所以单调递增",
     "label": "概念不清"},
    {"stem": "若 $\\log_a 2 < 1$，求 $a$ 的取值范围（$a>0$ 且 $a\\neq1$）。", "options": None,
     "answer": "$a>2$", "my_answer": "$0<a<1$ 时函数递减，得 $2>a$，所以 $0<a<2$",
     "label": "概念不清"},
    {"stem": "求 $\\sqrt{12}+\\sqrt{27}$ 的值。", "options": None,
     "answer": "$5\\sqrt{3}$", "my_answer": "原式 $=\\sqrt{12+27}=\\sqrt{39}$",
     "label": "概念不清"},
    # —— 计算失误 ×5（思路对、数值错）——
    {"stem": "计算 $\\int_0^1 (2x+1)\\,dx$。", "options": None,
     "answer": "$2$", "my_answer": "$(x^2+x)\\big|_0^1=1$", "label": "计算失误"},
    {"stem": "解方程 $x^2-5x+6=0$。", "options": None,
     "answer": "$x=2$ 或 $x=3$", "my_answer": "因式分解得 $x=2$ 或 $x=-3$", "label": "计算失误"},
    {"stem": "计算 $\\sin 30^\\circ + \\cos 60^\\circ$。", "options": None,
     "answer": "$1$", "my_answer": "$\\sin30^\\circ+\\cos60^\\circ=0.5+0.5=0.5$",
     "label": "计算失误"},
    {"stem": "化简 $(a+b)^2-(a-b)^2$。", "options": None,
     "answer": "$4ab$", "my_answer": "$a^2+2ab+b^2-a^2-2ab+b^2=2ab$", "label": "计算失误"},
    {"stem": "求等比数列 $2,4,8,\\dots$ 的前 5 项和。", "options": None,
     "answer": "$62$", "my_answer": "$S_5=\\frac{2(1-2^5)}{1-2}=58$", "label": "计算失误"},
    # —— 审题偏差 ×5（条件/所求看错）——
    {"stem": "等差数列 $\\{a_n\\}$ 中 $a_1=2$，公差 $d=3$，求 $a_{10}$。", "options": None,
     "answer": "$29$", "my_answer": "$a_5=2+4\\times3=14$，所以填 14", "label": "审题偏差"},
    {"stem": "已知 $a=3$，$b=-2$，求 $a^2-b$ 的值。", "options": None,
     "answer": "$11$", "my_answer": "$a^2-b=3^2-2=7$", "label": "审题偏差"},
    {"stem": "某商品先涨价 10% 再降价 10%，现价与原价相比如何？", "options": None,
     "answer": "下降 1%", "my_answer": "先涨价 10%，所以现价比原价上涨 10%", "label": "审题偏差"},
    {"stem": "求函数 $y=x^2$ 在区间 $[-2,1]$ 上的最大值。", "options": None,
     "answer": "$4$", "my_answer": "因为 $x\\le 1$，最大值在 $x=1$ 处取到，为 1", "label": "审题偏差"},
    {"stem": "已知集合 $A=\\{1,2,5\\}$，$B=\\{2,3,5\\}$，求 $A\\cap B$ 中元素的个数。", "options": None,
     "answer": "$2$", "my_answer": "$A\\cap B=\\{2,3,5\\}$，共 3 个", "label": "审题偏差"},
    # —— 方法不当 ×5（路径/论证方法错）——
    {"stem": "若 $x>0$，求 $x+\\frac{4}{x}$ 的最小值。", "options": None,
     "answer": "$4$", "my_answer": "x 越大 $\\frac{4}{x}$ 越小，x 趋近 0 时最小，最小值是 0",
     "label": "方法不当"},
    {"stem": "求函数 $f(x)=x^3-3x$ 的极值点。", "options": None,
     "answer": "$x=-1$ 为极大值点，$x=1$ 为极小值点",
     "my_answer": "$f(x)$ 是奇函数，图像关于原点对称，所以在 R 上单调，无极值点",
     "label": "方法不当"},
    {"stem": "证明：对任意实数 $x$，$x^2+2x+3>0$。", "options": None,
     "answer": "配方得 $(x+1)^2+2>0$",
     "my_answer": "取 x=0 代入得 3>0 成立，所以对任意 x 都成立", "label": "方法不当"},
    {"stem": "证明 $\\sqrt{2}$ 是无理数。", "options": None,
     "answer": "反证法：设 $\\sqrt2=\\frac{p}{q}$ 为既约分数，则 $p^2=2q^2$，推出 $p,q$ 同为偶数，矛盾",
     "my_answer": "用计算器算出 $\\sqrt2=1.41421356\\dots$，小数无限不循环，所以是无理数",
     "label": "方法不当"},
    {"stem": "解不等式 $\\frac{x-1}{x+2}>0$。", "options": None,
     "answer": "$x>1$ 或 $x<-2$",
     "my_answer": "两边乘 $x+2$ 得 $x-1>0$，即 $x>1$", "label": "方法不当"},
    # —— 知识遗忘 ×5（公式本身记错/记不起）——
    {"stem": "写出两角和正弦公式 $\\sin(\\alpha+\\beta)=$。", "options": None,
     "answer": "$\\sin\\alpha\\cos\\beta+\\cos\\alpha\\sin\\beta$",
     "my_answer": "sinαcosβ-cosαsinβ", "label": "知识遗忘"},
    {"stem": "写出等差数列前 $n$ 项和公式 $S_n=$。", "options": None,
     "answer": "$\\frac{n(a_1+a_n)}{2}$", "my_answer": "n(a1+an)", "label": "知识遗忘"},
    {"stem": "写出 $\\log_a(MN)=$（$a>0,a\\neq1$）。", "options": None,
     "answer": "$\\log_a M+\\log_a N$", "my_answer": "log_a M · log_a N", "label": "知识遗忘"},
    {"stem": "写出余弦定理 $c^2=$。", "options": None,
     "answer": "$a^2+b^2-2ab\\cos C$", "my_answer": "a^2+b^2", "label": "知识遗忘"},
    {"stem": "写出导数的幂函数法则 $(x^n)'=$。", "options": None,
     "answer": "$nx^{n-1}$", "my_answer": "x^{n-1}", "label": "知识遗忘"},
    # —— 时间不足 ×5（方向对但作答中途截断、无最终结论）——
    {"stem": "求函数 $f(x)=x^2-2x+3$ 在 $[0,3]$ 上的值域。", "options": None,
     "answer": "$[2,6]$", "my_answer": "配方得 (x-1)^2+2，所以最小 2", "label": "时间不足"},
    {"stem": "求过点 $(1,2)$ 且斜率为 3 的直线方程。", "options": None,
     "answer": "$y=3x-1$", "my_answer": "y-2=3(x-1)，展开", "label": "时间不足"},
    {"stem": "求数列 $1,\\frac{1}{2},\\frac{1}{4},\\dots$ 的前 4 项和。", "options": None,
     "answer": "$\\frac{15}{8}$", "my_answer": "1+1/2+1/4", "label": "时间不足"},
    {"stem": "已知 $A(1,2)$，$B(4,6)$，求 $|AB|$。", "options": None,
     "answer": "$5$", "my_answer": "√(9+16)=√25", "label": "时间不足"},
    {"stem": "求 $\\lim_{x\\to 0}\\frac{\\sin x}{x}$。", "options": None,
     "answer": "$1$", "my_answer": "用洛必达，cos x / 1", "label": "时间不足"},
]


def login(c: httpx.Client) -> dict[str, str]:
    # 已注册时 register 会 4xx；只要 login 成功即可，不视为错误
    c.post(
        f"{BASE}/auth/register",
        json={
            "username": USER,
            "password": PWD,
            "nickname": "S4-3验收",
            "grade": "高二",
            "role": "student",
        },
    )
    resp = c.post(f"{BASE}/auth/login", json={"username": USER, "password": PWD})
    resp.raise_for_status()
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}


def _normalized(text: str) -> str:
    """去空白后比：题库落库时做过规范化，原样字符串相等太脆。"""
    return "".join(text.split())


def _find_question(c: httpx.Client, h: dict[str, str], stem: str) -> int | None:
    """409 之后回查既有题。

    判重有两道闸（stem_hash + 余弦 ≥0.92），语义重复但字面不同的题也会 409，
    所以这里按字符相似度取最像的一条，而不是要求题干完全相等。
    含 LaTeX 的题干做 ILIKE 子串常常打不中，退化成纯中文片段再查一轮。
    """
    target = _normalized(stem)
    cjk = "".join(ch for ch in stem if "\u4e00" <= ch <= "\u9fff")
    keywords = [stem[:20], cjk[:8], cjk[:4]]
    best_id: int | None = None
    best_ratio = 0.0
    seen: set[int] = set()
    for keyword in keywords:
        if not keyword:
            continue
        items = c.get(
            f"{BASE}/questions",
            headers=h,
            params={"subject_id": SUBJECT_ID, "keyword": keyword, "page_size": 100},
        ).json()["data"]["items"]
        for item in items:
            qid = int(item["id"])
            if qid in seen:
                continue
            seen.add(qid)
            ratio = SequenceMatcher(None, _normalized(item["stem_md"]), target).ratio()
            if ratio > best_ratio:
                best_id, best_ratio = qid, ratio
    return best_id if best_ratio >= 0.6 else None


def ensure_question(c: httpx.Client, h: dict[str, str], case: dict) -> int:
    body: dict = {
        "subject_id": SUBJECT_ID,
        "stem_md": case["stem"],
        "qtype": "解答",
        "difficulty": 3,
        "origin": "upload",
        "answer_md": case["answer"],
    }
    if case["options"]:
        body["options"] = case["options"]
        body["qtype"] = "单选"
    resp = c.post(f"{BASE}/questions", headers=h, json=body)
    if resp.status_code == 201:
        return int(resp.json()["data"]["id"])
    if resp.status_code == 409:
        found = _find_question(c, h, case["stem"])
        if found is not None:
            return found
        raise SystemExit(f"重复题但回查不到：{case['stem'][:40]}")
    raise SystemExit(f"建题失败 {resp.status_code}: {resp.text[:300]}")


def main() -> int:
    cases_out: list[dict] = []
    with httpx.Client(timeout=120.0) as c:
        h = login(c)
        for index, case in enumerate(CASES, start=1):
            question_id = ensure_question(c, h, case)
            resp = c.post(
                f"{BASE}/mistakes",
                headers=h,
                json={"question_id": question_id, "my_answer_md": case["my_answer"]},
            )
            if resp.status_code not in (200, 201):
                raise SystemExit(f"建错题失败 {resp.status_code}: {resp.text[:300]}")
            data = resp.json()["data"]
            cases_out.append(
                {
                    "index": index,
                    "mistake_id": int(data["id"]),
                    "question_id": question_id,
                    "label": case["label"],
                    "my_answer_md": case["my_answer"],
                    "stem": case["stem"],
                }
            )
            print(f"[{index:02d}/{len(CASES)}] mistake={data['id']} label={case['label']}")

    OUT_PATH.write_text(
        json.dumps({"subject_id": SUBJECT_ID, "user": USER, "cases": cases_out},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"写出 {OUT_PATH}（{len(cases_out)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())