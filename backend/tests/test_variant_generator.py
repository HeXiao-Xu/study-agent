"""S4-4 生成适配器：严格 JSON、条数、选项规则、重试。"""
from __future__ import annotations

import pytest

from app.ai.gen.variant_generator import (
    GenerationContext,
    GeneratedVariant,
    MAX_TOKENS,
    VariantGenerationError,
    generate_variants,
    render_prompt,
)


class FakeClient:
    def __init__(self, payloads: list[str]):
        self.payloads = payloads
        self.calls: list[dict] = []

    def chat(self, messages, *, temperature=0.0, max_tokens=None, scene=""):
        self.calls.append(
            {
                "messages": messages,
                "scene": scene,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )

        class _Resp:
            text = self.payloads.pop(0)

        return _Resp()


def _ctx(**overrides) -> GenerationContext:
    base = dict(
        stem_md="等差数列 $\\{a_n\\}$ 中 $a_1=2$，公差 $d=3$，求 $a_{10}$。",
        options=[],
        correct_answer_md="$29$",
        kp_names=["等差数列"],
        cause_type="审题偏差",
        qtype="解答",
        difficulty=2,
        count=2,
    )
    base.update(overrides)
    return GenerationContext(**base)


GOOD = (
    '{"items":['
    '{"stem_md":"等差数列 $a_1=1$，公差 $d=2$，求 $a_7$。","options":null,'
    '"answer_md":"$13$","analysis_md":"用 $a_n=a_1+(n-1)d$，得 $a_7=1+6\\\\times2=13$。",'
    '"qtype":"解答","difficulty":3},'
    '{"stem_md":"等差数列 $a_1=5$，公差 $d=-2$，求 $a_6$。","options":null,'
    '"answer_md":"$-5$","analysis_md":"$a_6=5+5\\\\times(-2)=-5$，注意符号。",'
    '"qtype":"解答","difficulty":1}'
    "]}"
)


def test_generate_variants_returns_parsed_items():
    client = FakeClient([GOOD])

    items = generate_variants(_ctx(), llm_client=client)

    assert [item.answer_md for item in items] == ["$13$", "$-5$"]
    assert all(isinstance(item, GeneratedVariant) for item in items)
    assert client.calls[0]["scene"] == "gen"
    assert client.calls[0]["temperature"] == 0.7


def test_generate_variants_prompt_contains_context():
    prompt = render_prompt(_ctx())

    assert "等差数列" in prompt
    assert "审题偏差" in prompt
    assert "$29$" in prompt


def test_generate_variants_retries_on_short_count():
    short = '{"items":[{"stem_md":"求 $1+2$ 的值。","options":null,"answer_md":"$3$",' \
            '"analysis_md":"直接相加得 3，注意不要抄错。","qtype":"解答","difficulty":1}]}'
    client = FakeClient([short, GOOD])

    items = generate_variants(_ctx(), llm_client=client)

    assert len(items) == 2
    assert len(client.calls) == 2


def test_generate_variants_retries_on_invalid_option_shape():
    bad = ('{"items":[{"stem_md":"下列哪个正确？","options":[{"key":"A","text":"1"}],'
           '"answer_md":"A","analysis_md":"只有一个选项，不合法但先看校验。","qtype":"单选","difficulty":2}]}')
    short_ok = '{"items":[{"stem_md":"求 $2+2$ 的值。","options":null,"answer_md":"$4$",' \
               '"analysis_md":"直接相加得 4，注意进位。","qtype":"解答","difficulty":1}]}'
    client = FakeClient([bad, short_ok])

    items = generate_variants(_ctx(count=1), llm_client=client)

    assert len(items) == 1
    assert len(client.calls) == 2


def test_generate_variants_raises_after_retries_exhausted():
    client = FakeClient(["不是 JSON", "还是不是 JSON", "仍不是 JSON"])

    with pytest.raises(VariantGenerationError):
        generate_variants(_ctx(), llm_client=client, max_retries=2)


def test_generate_variants_uses_roomy_token_budget():
    """真机验收：2000 会让 3 道解答题在 JSON 中途被截断，故留足 3500。"""
    client = FakeClient([GOOD])

    generate_variants(_ctx(), llm_client=client)

    assert client.calls[0]["max_tokens"] == MAX_TOKENS == 3500
