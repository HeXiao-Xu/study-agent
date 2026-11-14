"""S5-6 周报：Prompt 渲染、数字校验重试、失败包裹、空数据分支。"""
from __future__ import annotations

import pytest

from app.ai.llm import LLMClient, LLMError, LLMMessage, LLMResponse
from app.ai.report import weekly_report
from app.schemas.report import (
    NumberValidationOut,
    WeeklyMasteryOut,
    WeeklyReportOut,
    WeeklyStatsOut,
    WeeklyTotalsOut,
)
from app.services import report_service

STATS = {
    "period": {"from": "2026-11-08", "to": "2026-11-14", "days": 7},
    "totals": {"new_notes": 3},
}


class FakeLLM(LLMClient):
    def __init__(self, texts: list[str]) -> None:
        super().__init__(model="fake-weekly")
        self.texts = texts
        self.calls: list[list[LLMMessage]] = []
        self.scenes: list[str] = []

    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
        self.calls.append(list(messages))
        self.scenes.append(scene)
        return LLMResponse(text=self.texts.pop(0), model=self.model, total_tokens=10)


def _validator(text: str):
    tokens = report_service.extract_numbers(text)
    invalid = [
        token
        for token in tokens
        if token not in {"3", "2026", "11", "8", "14", "7"}
    ]
    return tokens, invalid


def test_render_prompt_includes_stats_and_number_rule():
    context = weekly_report.WeeklyReportContext(stats=STATS)
    prompt = weekly_report.render_prompt(context)
    assert "new_notes" in prompt
    assert "只能使用" in prompt
    assert "2026-11-08" in prompt


def test_generate_weekly_report_retries_after_invalid_number():
    llm = FakeLLM(["本周新增 999 条。", "本周新增 3 条。"])
    result = weekly_report.generate_weekly_report(
        weekly_report.WeeklyReportContext(stats=STATS),
        validator=_validator,
        llm_client=llm,
    )
    assert result.text == "本周新增 3 条。"
    assert result.attempts == 2
    assert len(llm.calls) == 2
    assert llm.scenes == ["report", "report"]
    assert "999" in llm.calls[1][-1].content
    assert result.invalid_numbers == []


def test_generate_weekly_report_raises_after_retries_exhausted():
    llm = FakeLLM(["999", "999", "999"])
    with pytest.raises(weekly_report.WeeklyReportError):
        weekly_report.generate_weekly_report(
            weekly_report.WeeklyReportContext(stats=STATS),
            validator=_validator,
            llm_client=llm,
        )
    assert len(llm.calls) == 3


def test_generate_weekly_report_wraps_llm_error():
    class BrokenLLM(LLMClient):
        def __init__(self):
            super().__init__(model="broken")

        def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
            raise LLMError("network down")

    with pytest.raises(weekly_report.WeeklyReportError):
        weekly_report.generate_weekly_report(
            weekly_report.WeeklyReportContext(stats=STATS),
            validator=_validator,
            llm_client=BrokenLLM(),
        )


def test_generate_weekly_empty_returns_without_llm(monkeypatch):
    empty = WeeklyStatsOut(
        totals=WeeklyTotalsOut(
            new_notes=0,
            reviews_done=0,
            new_mistakes=0,
            mastered_mistakes=0,
            mistakes_net=0,
        ),
        active_days=0,
        mastery=WeeklyMasteryOut(
            assessed_kp_count=0,
            avg_mastery=None,
            weak_modules=[],
            weak_kps=[],
        ),
        trend=[],
    )
    monkeypatch.setattr(report_service, "build_weekly_stats", lambda *a, **k: empty)
    out = report_service.generate_weekly(session=object(), user_id=62)
    assert out.generated_by == "empty"
    assert out.report_md == report_service.EMPTY_REPORT_MD
    assert out.validation == NumberValidationOut(
        ok=True, attempts=0, checked_numbers=[], invalid_numbers=[]
    )


def test_generate_weekly_uses_adapter(monkeypatch):
    stats = WeeklyStatsOut(
        totals=WeeklyTotalsOut(
            new_notes=3,
            reviews_done=0,
            new_mistakes=0,
            mastered_mistakes=0,
            mistakes_net=0,
        ),
        active_days=1,
        mastery=WeeklyMasteryOut(
            assessed_kp_count=0,
            avg_mastery=None,
            weak_modules=[],
            weak_kps=[],
        ),
        trend=[],
    )
    monkeypatch.setattr(report_service, "build_weekly_stats", lambda *a, **k: stats)
    monkeypatch.setattr(
        weekly_report,
        "generate_weekly_report",
        lambda context, *, validator, llm_client=None: weekly_report.WeeklyReportResult(
            text="本周新增 3 条。",
            attempts=1,
            checked_numbers=["3"],
            invalid_numbers=[],
        ),
    )
    out = report_service.generate_weekly(session=object(), user_id=50)
    assert out.generated_by == "llm"
    assert out.report_md == "本周新增 3 条。"
    assert out.validation.ok is True
    assert out.validation.checked_numbers == ["3"]