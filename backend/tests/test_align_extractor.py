"""S2-10 LLM 候选内抽取：FakeLLM，不真实调用。"""
from __future__ import annotations

import pytest

from app.ai.align.extractor import AlignError, extract_matches
from app.ai.align.scoring import Candidate
from app.ai.llm import LLMClient, LLMResponse


class FakeLLM(LLMClient):
    def __init__(self, texts: list[str]) -> None:
        super().__init__(model="fake-llm")
        self.texts = list(texts)
        self.calls: list[list] = []

    def chat(
        self, messages, *, temperature=None, max_tokens=None, scene="qa"
    ) -> LLMResponse:
        self.calls.append(messages)
        text = self.texts.pop(0)
        return LLMResponse(text=text, model="fake-llm", total_tokens=10)


def _candidates() -> list[Candidate]:
    return [
        Candidate(1, "MATH-FUNC-02", "函数的单调性", "函数 / 函数的单调性", 0.8, 1.0, 0.3),
        Candidate(2, "MATH-FUNC-03", "函数的奇偶性", "函数 / 函数的奇偶性", 0.6, 0.0, 0.3),
    ]


def test_extract_valid_json_returns_matches() -> None:
    llm = FakeLLM(['{"matches":[{"kp_id":1,"confidence":0.9,"evidence":"单调性"}]}'])
    matches = extract_matches(
        note_title="单调性", note_excerpt="讨论单调性", candidates=_candidates(), llm_client=llm
    )
    assert [(m.kp_id, m.confidence) for m in matches] == [(1, 0.9)]


def test_extract_drops_unknown_kp_id() -> None:
    llm = FakeLLM(['{"matches":[{"kp_id":99,"confidence":0.9,"evidence":"x"}]}'])
    assert extract_matches(
        note_title="t", note_excerpt="x", candidates=_candidates(), llm_client=llm
    ) == []


def test_extract_dedupes_same_kp() -> None:
    llm = FakeLLM(
        ['{"matches":[{"kp_id":1,"confidence":0.9,"evidence":"a"},'
         '{"kp_id":1,"confidence":0.8,"evidence":"b"}]}']
    )
    matches = extract_matches(
        note_title="t", note_excerpt="x", candidates=_candidates(), llm_client=llm
    )
    assert len(matches) == 1
    assert matches[0].confidence == 0.9


def test_extract_retries_after_invalid_confidence() -> None:
    llm = FakeLLM(
        [
            '{"matches":[{"kp_id":1,"confidence":1.5,"evidence":"a"}]}',
            '{"matches":[{"kp_id":1,"confidence":0.8,"evidence":"a"}]}',
        ]
    )
    matches = extract_matches(
        note_title="t", note_excerpt="x", candidates=_candidates(), llm_client=llm
    )
    assert len(matches) == 1
    assert len(llm.calls) == 2


def test_extract_retries_after_invalid_json() -> None:
    llm = FakeLLM(["不是 JSON", '{"matches":[]}'])
    assert extract_matches(
        note_title="t", note_excerpt="x", candidates=_candidates(), llm_client=llm
    ) == []
    assert len(llm.calls) == 2


def test_extract_raises_after_three_invalid_responses() -> None:
    llm = FakeLLM(["bad", "bad", "bad"])
    with pytest.raises(AlignError, match="抽取失败"):
        extract_matches(
            note_title="t", note_excerpt="x", candidates=_candidates(), llm_client=llm
        )
    assert len(llm.calls) == 3


def test_extract_prompt_contains_candidates_and_excerpt() -> None:
    llm = FakeLLM(['{"matches":[]}'])
    extract_matches(
        note_title="单调性复习",
        note_excerpt="讨论单调性",
        candidates=_candidates(),
        llm_client=llm,
    )
    prompt = llm.calls[0][0].content
    assert "MATH-FUNC-02" in prompt
    assert "讨论单调性" in prompt
    assert "只能" in prompt


def test_extract_empty_candidates_skips_llm() -> None:
    llm = FakeLLM([])
    assert extract_matches(
        note_title="t", note_excerpt="x", candidates=[], llm_client=llm
    ) == []
    assert llm.calls == []