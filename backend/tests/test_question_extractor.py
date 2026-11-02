"""S4-1 单题结构化抽取：一套 schema 覆盖单题与整卷，非法输出必须重试。"""
from __future__ import annotations

import json

import pytest

from app.ai.extract import question_extractor
from app.ai.extract.question_extractor import QuestionExtractError, extract_questions


class FakeLLM:
    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls = 0
        self.scenes: list[str] = []

    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
        from app.ai.llm import LLMResponse

        self.calls += 1
        self.scenes.append(scene)
        text = self.texts.pop(0) if self.texts else self.texts[-1]
        return LLMResponse(text=text, model="fake-llm", total_tokens=10)


def single(**overrides) -> str:
    payload = {
        "stem_md": "已知函数 $f(x)=x^2$，求 $f(1)$。",
        "options": None,
        "answer_md": "1",
        "analysis_md": "代入即可。",
        "qtype": "解答",
        "difficulty": 2,
        "kp_names": ["函数的单调性"],
        "answer_source": "paper",
    }
    payload.update(overrides)
    return json.dumps({"questions": [payload]}, ensure_ascii=False)


CHOICE = {
    "stem_md": "已知集合 A={1,2}，B={2,3}，则 A∩B=（ ）",
    "options": [{"key": "A", "text": "{1}"}, {"key": "B", "text": "{2}"}],
    "answer_md": "B",
    "analysis_md": None,
    "qtype": "单选",
    "difficulty": 1,
    "kp_names": ["集合的运算"],
    "answer_source": "paper",
}


def test_parses_single_question() -> None:
    result = extract_questions(question_text="1. 已知函数...", llm_client=FakeLLM(single()))
    assert len(result.questions) == 1
    assert result.questions[0].stem_md.startswith("已知函数")
    assert result.questions[0].answer_source == "paper"
    assert result.truncated is False


def test_parses_block_mode_multiple() -> None:
    text = json.dumps({"questions": [CHOICE, CHOICE]}, ensure_ascii=False)
    result = extract_questions(
        question_text="整卷原文", mode="block", expected_count=2, llm_client=FakeLLM(text)
    )
    assert len(result.questions) == 2


def test_choice_with_single_option_retries_then_succeeds() -> None:
    broken = json.dumps({"questions": [{**CHOICE, "options": [{"key": "A", "text": "x"}]}]}, ensure_ascii=False)
    good = json.dumps({"questions": [CHOICE]}, ensure_ascii=False)
    client = FakeLLM(broken, good)
    result = extract_questions(question_text="1. 选择题", llm_client=client)
    assert client.calls == 2
    assert len(result.questions) == 1


def test_answer_letter_outside_options_retries() -> None:
    broken = json.dumps({"questions": [{**CHOICE, "answer_md": "E"}]}, ensure_ascii=False)
    good = json.dumps({"questions": [CHOICE]}, ensure_ascii=False)
    client = FakeLLM(broken, good)
    assert len(extract_questions(question_text="1. 选择题", llm_client=client).questions) == 1
    assert client.calls == 2


def test_options_on_blank_question_retries() -> None:
    broken = json.dumps({"questions": [{"stem_md": "填空题干内容", "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}],
                                        "answer_md": "1", "analysis_md": None, "qtype": "填空",
                                        "difficulty": 2, "kp_names": [], "answer_source": "paper"}]}, ensure_ascii=False)
    client = FakeLLM(broken, single(qtype="填空", answer_md="2", options=None))
    assert len(extract_questions(question_text="1. 填空", llm_client=client).questions) == 1
    assert client.calls == 2


def test_three_invalid_attempts_raise() -> None:
    client = FakeLLM("<html>不是 JSON</html>", "<html>还是不是</html>", "{}")
    with pytest.raises(QuestionExtractError):
        extract_questions(question_text="1. 题", llm_client=client)
    assert client.calls == 3


def test_single_mode_with_two_questions_retries() -> None:
    two = json.dumps({"questions": [CHOICE, CHOICE]}, ensure_ascii=False)
    client = FakeLLM(two, single())
    result = extract_questions(question_text="1. 题", llm_client=client)
    assert client.calls == 2
    assert len(result.questions) == 1


def test_block_mode_truncates_to_expected_count() -> None:
    text = json.dumps({"questions": [CHOICE, CHOICE, CHOICE]}, ensure_ascii=False)
    result = extract_questions(
        question_text="整卷", mode="block", expected_count=2, llm_client=FakeLLM(text)
    )
    assert len(result.questions) == 2
    assert result.truncated is True
    assert question_extractor.SCENE == "gen"