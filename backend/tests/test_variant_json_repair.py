"""S4-4 JSON 兜底解析：模型漏转义 LaTeX 反斜杠时的三档修复。"""
from __future__ import annotations

import pytest

from app.ai.gen.json_repair import loads_lenient_json


def test_parses_clean_json_untouched():
    assert loads_lenient_json('{"answer_md": "$4$"}') == {"answer_md": "$4$"}


def test_repairs_invalid_escape():
    """`\\sqrt` 不是合法 JSON 转义：修成字面反斜杠后应解析成功。"""
    text = '{"answer_md": "\\(0,1)\\)", "reasoning_md": "\\sqrt{7} > 2"}'

    payload = loads_lenient_json(text)

    assert payload["reasoning_md"] == "\\sqrt{7} > 2"


def test_repairs_newline_eaten_latex_command():
    """`\\neq` 会被 json 当成换行+eq：不能把题面悄悄搞坏。"""
    text = '{"answer_md": "$a>0$ 且 $a\\neq 1$"}'

    payload = loads_lenient_json(text)

    assert payload["answer_md"] == "$a>0$ 且 $a\\neq 1$"
    assert "\n" not in payload["answer_md"]


def test_repairs_formfeed_eaten_frac():
    """`\\frac` 会被 json 当成换页符：修复后应是字面反斜杠。"""
    text = '{"answer_md": "$\\frac{3}{2}$"}'

    payload = loads_lenient_json(text)

    assert payload["answer_md"] == "$\\frac{3}{2}$"
    assert "\x0c" not in payload["answer_md"]


def test_keeps_intentional_newlines_in_chinese_text():
    """正常换行后面的中文不该被当成 LaTeX 命令。"""
    text = '{"analysis_md": "第一步：求导\\n所以单调递增。"}'

    payload = loads_lenient_json(text)

    assert payload["analysis_md"] == "第一步：求导\n所以单调递增。"


def test_raises_on_hopeless_json():
    with pytest.raises(ValueError):
        loads_lenient_json("{not json at all")


def test_leaves_properly_escaped_latex_untouched():
    """已正确写 `\\frac`/`\\infty` 的合法 JSON 必须原样通过（曾有正则误伤成 `\\\\frac`）。"""
    text = (
        '{"stem_md": "$f(x)=\\\\frac{2}{x+1}$ 在 $(-1, +\\\\infty)$ 上的单调性。",'
        ' "answer_md": "单调递减"}'
    )

    payload = loads_lenient_json(text)

    assert payload["stem_md"] == "$f(x)=\\frac{2}{x+1}$ 在 $(-1, +\\infty)$ 上的单调性。"


def test_repairs_mixed_valid_and_invalid_escapes():
    """一半写对一半写错时，只修漏转义的那部分。"""
    text = '{"answer_md": "$\\\\frac{1}{2}$ 与 $x>\\sqrt{7}$"}'

    payload = loads_lenient_json(text)

    assert payload["answer_md"] == "$\\frac{1}{2}$ 与 $x>\\sqrt{7}$"
