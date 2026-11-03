"""S4-3 错因诊断适配器：JSON 解析、重试、unknown 强制、error_step 证据校验。"""
from __future__ import annotations

import pytest

from app.ai.analyze import (
    DiagnosisContext,
    MistakeAnalysisError,
    MistakeAnalysisResult,
    analyze_mistake,
    render_prompt,
)
from app.ai.json_utils import loads_json_object


class FakeClient:
    def __init__(self, payloads: list[str]):
        self.payloads = payloads
        self.calls: list[dict] = []

    def chat(self, messages, *, temperature=0.0, max_tokens=None, scene=""):
        self.calls.append({"messages": messages, "scene": scene, "temperature": temperature})

        class _Resp:
            text = self.payloads.pop(0)

        return _Resp()


def _ctx(**overrides) -> DiagnosisContext:
    base = dict(
        stem_md="已知函数 $f(x)=x^2-4x+3$，求对称轴",
        options=[],
        correct_answer_md="$x=2$",
        my_answer_md="对称轴 x=1",
        kp_names=["一元二次函数"],
        prerequisite_names=["函数"],
        notes=[],
    )
    base.update(overrides)
    return DiagnosisContext(**base)


GOOD = (
    '{"cause_type":"概念不清","secondary_causes":["计算失误"],'
    '"error_step":"你写的是「对称轴 x=1」，应为 x=2",'
    '"explanation_md":"配方得 $f(x)=(x-2)^2-1$，对称轴为 $x=2$。易错点是把顶点横坐标算错。",'
    '"review_advice_md":"复习配方法；对照笔记里的顶点公式。","confidence":0.82}'
)


def test_analyze_mistake_parses_valid_json():
    client = FakeClient([GOOD])

    result = analyze_mistake(_ctx(), llm_client=client)

    assert isinstance(result, MistakeAnalysisResult)
    assert result.cause_type.value == "概念不清"
    assert [c.value for c in result.secondary_causes] == ["计算失误"]
    assert "x=1" in (result.error_step or "")
    assert client.calls[0]["scene"] == "mistake"
    assert client.calls[0]["temperature"] == 0.2
    assert len(client.calls) == 1


def test_analyze_mistake_retries_then_raises():
    client = FakeClient(["不是 JSON", "还是不是"])

    with pytest.raises(MistakeAnalysisError):
        analyze_mistake(_ctx(), llm_client=client, max_retries=1)

    assert len(client.calls) == 2


def test_missing_answer_forces_unknown_even_if_model_guesses():
    result = analyze_mistake(_ctx(my_answer_md=None), llm_client=FakeClient([GOOD]))

    assert result.cause_type.value == "unknown"
    assert result.secondary_causes == []
    assert result.error_step is None


def test_blank_answer_also_forces_unknown():
    result = analyze_mistake(_ctx(my_answer_md="   "), llm_client=FakeClient([GOOD]))

    assert result.cause_type.value == "unknown"


def test_secondary_causes_dedup_and_drop_primary():
    payload = (
        '{"cause_type":"概念不清","secondary_causes":["概念不清","计算失误","计算失误","时间不足"],'
        '"error_step":null,"explanation_md":"配方得 $f(x)=(x-2)^2-1$，对称轴 $x=2$。",'
        '"review_advice_md":"复习配方法，并对照笔记里的顶点公式。","confidence":0.5}'
    )

    result = analyze_mistake(_ctx(), llm_client=FakeClient([payload]))

    assert [c.value for c in result.secondary_causes] == ["计算失误", "时间不足"]


def test_secondary_causes_are_trimmed_to_two():
    payload = (
        '{"cause_type":"概念不清","secondary_causes":["计算失误","审题偏差","时间不足"],'
        '"error_step":null,"explanation_md":"配方得 $f(x)=(x-2)^2-1$，对称轴 $x=2$。",'
        '"review_advice_md":"复习配方法，并对照笔记里的顶点公式。","confidence":0.5}'
    )

    result = analyze_mistake(_ctx(), llm_client=FakeClient([payload]))

    assert [c.value for c in result.secondary_causes] == ["计算失误", "审题偏差"]


def test_error_step_without_student_text_is_dropped():
    payload = (
        '{"cause_type":"计算失误","secondary_causes":[],'
        '"error_step":"计算粗心","explanation_md":"配方得 $f(x)=(x-2)^2-1$，对称轴 $x=2$。",'
        '"review_advice_md":"复习配方法，并对照笔记里的顶点公式。","confidence":0.4}'
    )

    result = analyze_mistake(_ctx(), llm_client=FakeClient([payload]))

    assert result.error_step is None


def test_confidence_out_of_range_is_validation_error():
    payload = GOOD.replace('"confidence":0.82', '"confidence":1.5')

    with pytest.raises(MistakeAnalysisError):
        analyze_mistake(_ctx(), llm_client=FakeClient([payload, payload]), max_retries=1)


def test_unknown_primary_forces_empty_secondary():
    payload = (
        '{"cause_type":"unknown","secondary_causes":["计算失误"],'
        '"error_step":null,"explanation_md":"配方得 $f(x)=(x-2)^2-1$，对称轴 $x=2$。",'
        '"review_advice_md":"复习配方法，并对照笔记里的顶点公式。","confidence":0.3}'
    )

    result = analyze_mistake(_ctx(), llm_client=FakeClient([payload]))

    assert result.secondary_causes == []


def test_render_prompt_contains_context_blocks():
    text = render_prompt(
        _ctx(
            options=[("A", "x=1"), ("B", "x=2")],
            notes=[("二次函数笔记", "顶点式 $y=a(x-h)^2+k$")],
        )
    )

    assert "x^2-4x+3" in text
    assert "A. x=1" in text
    assert "二次函数笔记" in text
    assert "对称轴 x=1" in text


def test_render_prompt_without_answer_says_unknown_rule():
    text = render_prompt(_ctx(my_answer_md=None))

    assert "（学生没有提供作答）" in text
    assert 'cause_type 必须是 "unknown"' in text


def test_loads_json_object_strips_code_fence():
    assert loads_json_object('```json\n{"a":1}\n```') == {"a": 1}