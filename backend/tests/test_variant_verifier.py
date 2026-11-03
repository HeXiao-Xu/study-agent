"""S4-4 复算适配器：只喂题干（不含答案）、严格 JSON、重试。"""
from __future__ import annotations

import pytest

from app.ai.gen.variant_verifier import (
    MAX_TOKENS,
    VerifyContext,
    VariantVerificationError,
    render_verify_prompt,
    verify_answer,
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


def _ctx() -> VerifyContext:
    return VerifyContext(
        stem_md="等差数列 $a_1=1$，公差 $d=2$，求 $a_7$。", options=[]
    )


def test_render_verify_prompt_excludes_answer_and_analysis():
    prompt = render_verify_prompt(_ctx())

    assert "等差数列" in prompt
    assert "答案" in prompt  # 只是要求它作答，不能出现给定答案
    assert "$13$" not in prompt


def test_verify_answer_returns_answer_text():
    client = FakeClient(['{"answer_md":"$13$","reasoning_md":"$a_7=1+6\\\\times2=13$"}'])

    answer = verify_answer(_ctx(), llm_client=client)

    assert answer == "$13$"
    assert client.calls[0]["scene"] == "gen"


def test_verify_answer_retries_on_invalid_json():
    client = FakeClient(['{"wrong":1}', '{"answer_md":"$13$"}'])

    assert verify_answer(_ctx(), llm_client=client) == "$13$"


def test_verify_answer_raises_after_retries():
    client = FakeClient(["nope", "nope", "nope"])

    with pytest.raises(VariantVerificationError):
        verify_answer(_ctx(), llm_client=client, max_retries=2)


def test_verify_answer_uses_roomy_token_budget():
    """真机验收：对数不等式类题目的推理会写满上限（1200/1800 都被截断），故留 2600。"""
    client = FakeClient(['{"answer_md": "$a>1$", "reasoning_md": "略。"}'])

    verify_answer(_ctx(), llm_client=client)

    assert client.calls[0]["max_tokens"] == MAX_TOKENS == 2600


def test_verify_answer_truncates_overlong_reasoning_instead_of_failing():
    """reasoning 只展示、不参与比对：写超长要截断，不能把整道题判死（真机验收教训）。"""
    long_reasoning = "推理" * 1200
    client = FakeClient(['{"answer_md": "$a>1$", "reasoning_md": "' + long_reasoning + '"}'])

    answer = verify_answer(_ctx(), llm_client=client)

    assert answer == "$a>1$"
    assert len(client.payloads) == 0  # 没有触发重试
