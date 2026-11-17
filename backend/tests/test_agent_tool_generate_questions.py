"""S6-1 generate_questions：严格 JSON、重试、只出草稿。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.agents.tools import generate_questions as tool
from app.ai.agents.tools.base import ToolContext, ToolExecutionError

_VALID = (
    '{"questions":[{"stem_md":"已知 $f(x)=x^2$，求 $f(2)$。",'
    '"options":null,"answer_md":"4","analysis_md":"把 x=2 代入函数即可得到 4。",'
    '"qtype":"解答","difficulty":3}]}'
)


class _FakeLLM:
    def __init__(self, texts):  # noqa: ANN001
        self.texts = list(texts)
        self.calls: list[SimpleNamespace] = []

    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):  # noqa: ANN001
        self.calls.append(
            SimpleNamespace(
                temperature=temperature, max_tokens=max_tokens, scene=scene, messages=messages
            )
        )
        return SimpleNamespace(text=self.texts.pop(0))


def _ctx() -> ToolContext:
    class _Session:
        def get(self, model, pk):  # noqa: ANN001, ANN201
            if model.__name__ == "KnowledgePoint":
                return SimpleNamespace(id=pk, name="函数", subject_id=7)
            return SimpleNamespace(id=7, name="高中数学")

    return ToolContext(session=_Session(), user=SimpleNamespace(id=50))  # type: ignore[arg-type]


def test_generate_questions_returns_drafts_and_retries():
    llm = _FakeLLM(["不是 JSON", _VALID])
    out = tool.generate_questions(
        _ctx(), tool.GenerateQuestionsIn(kp_id=101, count=1), llm_client=llm
    )
    assert out.count == 1
    assert out.attempts == 2
    assert out.questions[0].answer_md == "4"
    assert out.prompt_version == "agent_gen_questions_v1"
    assert llm.calls[0].scene == "gen"
    assert llm.calls[0].max_tokens == 3500
    assert "函数" in llm.calls[0].messages[0].content


def test_generate_questions_exhausted_retries_raises():
    llm = _FakeLLM(["x", "y", "z"])
    with pytest.raises(ToolExecutionError):
        tool.generate_questions(
            _ctx(), tool.GenerateQuestionsIn(kp_id=101, count=1), llm_client=llm
        )


def test_generate_questions_count_mismatch_is_retried():
    llm = _FakeLLM(['{"questions":[]}', _VALID])
    out = tool.generate_questions(
        _ctx(), tool.GenerateQuestionsIn(kp_id=101, count=1), llm_client=llm
    )
    assert out.attempts == 2


def test_generate_questions_rejects_bad_option_shape():
    bad = _VALID.replace('"options":null', '"options":[{"key":"A","text":"x"}]')
    llm = _FakeLLM([bad, bad, bad])
    with pytest.raises(ToolExecutionError):
        tool.generate_questions(
            _ctx(), tool.GenerateQuestionsIn(kp_id=101, count=1), llm_client=llm
        )


def test_generate_questions_missing_kp_raises_404():
    class _Session:
        def get(self, model, pk):  # noqa: ANN001, ANN201
            return None

    ctx = ToolContext(session=_Session(), user=SimpleNamespace(id=50))  # type: ignore[arg-type]
    from app.core.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        tool.generate_questions(ctx, tool.GenerateQuestionsIn(kp_id=999))