import json

import pytest

from app.ai.llm.base import LLMResponse
from app.ai.vision import VisionError, extract_mistake


class FakeLLM:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.model = "qwen-vl-max-latest"

    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
        self.calls.append({"messages": messages, "scene": scene, "max_tokens": max_tokens})
        text = self.replies.pop(0)
        return LLMResponse(text=text, model=self.model, total_tokens=100, latency_ms=10)


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"0" * 64


GOOD = {
    "stem_md": "已知函数 $f(x)=x^{2}-4x+3$，求对称轴。",
    "options": None,
    "qtype": "解答",
    "correct_answer_md": None,
    "my_answer_md": "对称轴 x=2",
    "confidence": 0.86,
    "warnings": [],
}


def test_extract_mistake_returns_parsed_fields():
    client = FakeLLM([json.dumps(GOOD, ensure_ascii=False)])
    result = extract_mistake(_png_bytes(), "image/png", subject_name="高中数学", llm_client=client)
    assert result.stem_md.startswith("已知函数")
    assert result.my_answer_md == "对称轴 x=2"
    assert result.confidence == 0.86
    assert client.calls[0]["scene"] == "mistake_ocr"
    # 图片以 data URL 挂在 user 消息上
    assert client.calls[0]["messages"][-1].images[0].startswith("data:image/png;base64,")


def test_extract_mistake_retries_on_broken_json():
    client = FakeLLM(["not json", json.dumps(GOOD, ensure_ascii=False)])
    result = extract_mistake(_png_bytes(), "image/png", subject_name="高中数学", llm_client=client)
    assert result.qtype == "解答"
    assert len(client.calls) == 2


def test_extract_mistake_raises_after_two_retries():
    client = FakeLLM(["bad", "still bad", "nope"])
    with pytest.raises(VisionError) as excinfo:
        extract_mistake(_png_bytes(), "image/png", subject_name="高中数学", llm_client=client)
    assert len(client.calls) == 3  # 首次 + 2 次重试
    assert "3" in str(excinfo.value)


def test_extract_mistake_rejects_non_image_mime():
    with pytest.raises(VisionError):
        extract_mistake(_png_bytes(), "application/pdf", subject_name="高中数学", llm_client=FakeLLM([]))


def test_extract_mistake_rejects_oversized_image():
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (8 * 1024 * 1024)
    with pytest.raises(VisionError):
        extract_mistake(big, "image/png", subject_name="高中数学", llm_client=FakeLLM([]))


def test_choice_question_requires_two_options():
    bad = dict(GOOD, qtype="单选", options=[{"key": "A", "text": "1"}])
    client = FakeLLM([json.dumps(bad, ensure_ascii=False)] * 3)
    with pytest.raises(VisionError):
        extract_mistake(_png_bytes(), "image/png", subject_name="高中数学", llm_client=client)


def test_empty_answer_becomes_none():
    payload = dict(GOOD, my_answer_md=None)
    client = FakeLLM([json.dumps(payload, ensure_ascii=False)])
    result = extract_mistake(_png_bytes(), "image/png", subject_name="高中数学", llm_client=client)
    assert result.my_answer_md is None


def test_warnings_surface_on_result():
    payload = dict(GOOD, warnings=["作答无法辨认"])
    client = FakeLLM([json.dumps(payload, ensure_ascii=False)])
    result = extract_mistake(_png_bytes(), "image/png", subject_name="高中数学", llm_client=client)
    assert result.warnings == ["作答无法辨认"]


def test_extract_mistake_defaults_to_vision_client(monkeypatch):
    # brief Step 4 注：未注入 client 时必须走视觉模型工厂，而不是文本模型
    from app.ai.vision import mistake_ocr

    client = FakeLLM([json.dumps(GOOD, ensure_ascii=False)])
    monkeypatch.setattr(mistake_ocr, "get_vision_client", lambda: client)
    result = extract_mistake(_png_bytes(), "image/png", subject_name="高中数学")
    assert result.stem_md.startswith("已知函数")
    assert len(client.calls) == 1


def test_empty_string_my_answer_becomes_none():
    payload = dict(GOOD, my_answer_md="")
    client = FakeLLM([json.dumps(payload, ensure_ascii=False)])
    result = extract_mistake(_png_bytes(), "image/png", subject_name="高中数学", llm_client=client)
    assert result.my_answer_md is None


def test_whitespace_my_answer_becomes_none():
    payload = dict(GOOD, my_answer_md="   ")
    client = FakeLLM([json.dumps(payload, ensure_ascii=False)])
    result = extract_mistake(_png_bytes(), "image/png", subject_name="高中数学", llm_client=client)
    assert result.my_answer_md is None


def test_render_prompt_missing_variable_raises_vision_error(monkeypatch):
    from app.ai.vision import mistake_ocr

    monkeypatch.setattr(
        mistake_ocr._ENV,
        "get_template",
        lambda _name: mistake_ocr._ENV.from_string("{{ missing }}"),
    )
    with pytest.raises(VisionError):
        mistake_ocr.render_prompt(subject_name="高中数学")