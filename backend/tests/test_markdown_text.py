"""S2-5 content_text 派生规则（spec §6）。"""
from __future__ import annotations

from app.utils.markdown_text import to_plain_text


def test_plain_text_unchanged() -> None:
    assert to_plain_text("函数单调性 复习") == "函数单调性 复习"


def test_inline_math_removed() -> None:
    assert to_plain_text("设 $x^2+1$ 为正") == "设 为正"


def test_display_math_removed() -> None:
    assert to_plain_text("公式\n$$\n\\\\frac{1}{2}\n$$\n结尾") == "公式 结尾"


def test_latex_brackets_removed() -> None:
    assert to_plain_text("设 \\(x>0\\) 且 \\[y=1\\]") == "设 且"


def test_link_text_kept() -> None:
    assert to_plain_text("见[单调性定义](https://example.com/a)") == "见单调性定义"


def test_image_alt_kept() -> None:
    assert to_plain_text("![函数图像](a.png)") == "函数图像"


def test_markdown_markers_removed() -> None:
    text = "# 标题\n> 引用\n- 列表项\n---\n| a | b |"
    assert to_plain_text(text) == "标题 引用 列表项 a b"


def test_emphasis_markers_removed() -> None:
    assert to_plain_text("**重点** 与 __补充__ 和 ~~删掉~~") == "重点 与 补充 和 删掉"


def test_inline_code_content_kept() -> None:
    assert to_plain_text("用 `user_id` 过滤") == "用 user_id 过滤"


def test_fenced_code_kept_with_dollar() -> None:
    text = "示例\n```python\nprice = $1\n```\n完"
    plain = to_plain_text(text)
    assert "price = $1" in plain
    assert plain.startswith("示例")


def test_whitespace_collapsed() -> None:
    assert to_plain_text("a\n\n\n b\t\tc ") == "a b c"